"""LLM 抽取（DeepSeek，OpenAI 兼容）：技术实体/关系 + 中文新闻 tone。

- 用 `openai.OpenAI(base_url=..., api_key=...)` + `response_format={"type":"json_object"}`。
- 强制 JSON schema + 关系/实体白名单 + 温度 0 控幻觉；逐条 try/except 不阻断整批。
- 无 key 时由 ExtractStage 整体跳过（本类不处理 key 缺失）。
"""
import json
import logging
from typing import Any, Iterable

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from techtrend.extraction.schema import RELATION_RULES_LLM, TECH_ENTITY_TYPES, TECH_PAIR_RELATIONS

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """你是科技文档的实体与关系抽取器。只输出 JSON，不要输出其他内容。

实体类型（tail_type）限定为以下之一：
Technology（技术）、Method（方法）、Model（模型）、Framework（框架）、Dataset（数据集）、Institution（机构）、Person（人物）

关系（relation）限定为以下之一：
uses（使用）、improves（改进）、compares（对比）、belongs_to（属于）、targets（针对）、competes（竞品）、causes（因果）

规则：
1. 只抽取文档中明确提及的技术实体，不要臆造；tail 用实体规范名称（保持原文语言）。
2. 每条关系输出 {"relation": 关系, "tail": 实体名, "tail_type": 实体类型}。
3. 若没有可抽取的关系，输出 {"triples": []}。
4. 严格输出 JSON：{"triples": [...]}。"""

_TECHPAIR_SYSTEM_PROMPT = """你是科技文档的「技术间定向关系」抽取器。只输出 JSON。
输入已给出本文档识别到的技术实体名列表。
关系（relation）限定：uses（A 使用 B）/ improves（A 改进 B）/ compares（A 对比 B）/
targets（A 针对 B）/ competes（A 与 B 竞品）。
规则：
1. head、tail 都必须是「技术实体名列表」里出现的实体（规范名，保持原文语言）。
2. 只抽文档中明确陈述的定向关系，不臆造；方向必须符合语义（A→B 与 B→A 不同）。
3. 无定向关系输出 {"pairs": []}。
4. 严格输出 JSON：{"pairs": [{"head": 实体A, "relation": 关系, "tail": 实体B}]}。"""

_TONE_PROMPT = """你是中文科技新闻的情感分析器。判断下面这条新闻对所述技术/公司/事件的态度倾向。
只输出 JSON：{"tone": 数值}，数值在 -1（强烈负面）到 1（强烈正面）之间，0 表示中性。
不要输出其他内容。"""


def _should_retry(exc: BaseException) -> bool:
    try:
        status = exc.status_code
    except AttributeError:
        return False
    return status == 429 or status >= 500


def _parse_json(content: str) -> dict | None:
    """解析模型返回的 JSON（容忍 markdown 代码围栏）。"""
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 兜底：取首个 { ... } 块
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
        return None


class LLMExtractor:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> None:
        from openai import OpenAI  # 延迟导入，避免未安装 openai 时 import 报错

        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature

    @retry(
        retry=retry_if_exception(_should_retry),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        reraise=True,
    )
    def _chat(self, system: str, user: str) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content or ""

    @staticmethod
    def _doc_text(doc: dict) -> str:
        title = doc.get("title") or ""
        body = doc.get("abstract") or doc.get("text") or doc.get("description") or ""
        return f"标题：{title}\n正文：{body}".strip()

    # ---- 抽取 ----
    def extract(self, doc: dict) -> list[dict]:
        """单文档 → 技术三元组片段 [{relation, tail, tail_type}]。"""
        try:
            content = self._chat(_SYSTEM_PROMPT, self._doc_text(doc))
        except Exception as exc:  # noqa: BLE001 —— 单条失败不阻断整批
            log.warning("LLM 抽取失败（id=%s）：%s", doc.get("id"), exc)
            return []
        data = _parse_json(content) or {}
        triples = data.get("triples") or []
        return self._validate(triples)

    def extract_batch(self, docs: list[dict]) -> list[dict]:
        out: list[dict] = []
        for doc in docs:
            out.extend(self.extract(doc))
        return out

    def extract_tech_pairs(
        self,
        doc: dict,
        known_tech_names: list[str],
        relations: Iterable[str] | None = None,
    ) -> list[dict]:
        """单文档 → 定向 tech→tech 三元组 [{"head","relation","tail"}]（head/tail 均为技术实体名）。

        known_tech_names：该文档已抽取到的技术实体名（doc→tech 的 tail 名），head/tail 都必须在其内。
        relations：定向关系白名单（缺省用 TECH_PAIR_RELATIONS）。
        """
        if not known_tech_names:
            return []
        known_set = {n.strip() for n in known_tech_names if n and n.strip()}
        if not known_set:
            return []
        allowed = set(relations) if relations else set(TECH_PAIR_RELATIONS)
        user = self._doc_text(doc) + "\n已识别技术实体：[" + ", ".join(sorted(known_set)) + "]"
        try:
            content = self._chat(_TECHPAIR_SYSTEM_PROMPT, user)
        except Exception as exc:  # noqa: BLE001 —— 单条失败不阻断整批
            log.warning("LLM 定向对抽取失败（id=%s）：%s", doc.get("id"), exc)
            return []
        data = _parse_json(content) or {}
        pairs = data.get("pairs") or []
        out: list[dict] = []
        seen: set[tuple] = set()
        for p in pairs:
            if not isinstance(p, dict):
                continue
            head = (p.get("head") or "").strip()
            relation = p.get("relation")
            tail = (p.get("tail") or "").strip()
            if relation not in allowed:
                continue
            if head not in known_set or tail not in known_set:
                continue
            if head == tail:
                continue
            key = (head, relation, tail)
            if key in seen:
                continue
            seen.add(key)
            out.append({"head": head, "relation": relation, "tail": tail})
        return out

    def extract_tone(self, text: str) -> float | None:
        """中文新闻情感（-1..1），失败返回 None。"""
        try:
            content = self._chat(_TONE_PROMPT, text[:2000])
        except Exception as exc:  # noqa: BLE001
            log.warning("LLM tone 失败：%s", exc)
            return None
        data = _parse_json(content) or {}
        tone = data.get("tone")
        try:
            return max(-1.0, min(1.0, float(tone)))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _validate(triples: list[dict]) -> list[dict]:
        """白名单过滤 + 去重（关系/实体类型 + tail 名）。"""
        seen: set[tuple] = set()
        out: list[dict] = []
        for t in triples:
            relation = t.get("relation")
            tail = (t.get("tail") or "").strip()
            tail_type = t.get("tail_type")
            if relation not in RELATION_RULES_LLM:
                continue
            if tail_type not in TECH_ENTITY_TYPES:
                continue
            if not tail:
                continue
            key = (relation, tail, tail_type)
            if key in seen:
                continue
            seen.add(key)
            out.append({"relation": relation, "tail": tail, "tail_type": tail_type})
        return out
