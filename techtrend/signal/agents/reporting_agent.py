"""Agent responsible for summarizing forecast results using DeepSeek LLM."""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from techtrend.config import PROJECT_ROOT

from techtrend.signal.config import PipelineConfig
from techtrend.signal.http_client import PoliteApiClient

class ReportingAgent:
    """Summarizes backtest and ranking results using DeepSeek."""

    def __init__(self, cfg: PipelineConfig):
        self.cfg = cfg
        self.ranking_path = self.cfg.reports_path / "forecast_ranking_latest.json"
        self.backtest_path = self.cfg.reports_path / "backtest_latest.json"
        self.report_path = self.cfg.reports_path / "final_report.md"
        
        # Load environment variables (e.g. from .env)
        load_dotenv(PROJECT_ROOT / ".env")

    async def _call_deepseek(self, prompt: str) -> str:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            return "Error: DEEPSEEK_API_KEY is not set in environment or .env file."

        # Use the PoliteApiClient with standard HTTP settings.
        # We don't want exponential backoff for an LLM call if it fails permanently,
        # but the built-in retries for 500s or 429s are helpful.
        settings = {
            "timeout_seconds": 60,
            "max_retries": 2,
        }
        
        url = "https://api.deepseek.com/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}"
        }
        body = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "You are a senior data analyst summarizing technology trends. Write your report in Markdown format."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.5
        }

        # PoliteApiClient needs a cache directory, we can use the interim path
        cache_dir = self.cfg.interim_path / "llm_cache"
        async with PoliteApiClient(cache_dir, settings=settings) as client:
            try:
                response = await client.post_json(
                    url,
                    body=body,
                    cache_key="deepseek_report_latest",
                    extra_headers=headers
                )
                if response.status_code == 200:
                    choices = response.payload.get("choices", [])
                    if choices:
                        return choices[0]["message"]["content"]
                    else:
                        return f"Error: Unexpected API payload format: {response.payload}"
                else:
                    return f"API Error: HTTP {response.status_code} - {response.payload}"
            except Exception as e:
                return f"Error connecting to DeepSeek API: {str(e)}"

    def run(self) -> None:
        """Execute the reporting agent logic."""
        if not self.ranking_path.exists() or not self.backtest_path.exists():
            print("Skipping report generation: Ranking or backtest JSON files not found.")
            return

        print("Loading results for LLM summary...")
        with open(self.ranking_path, "r", encoding="utf-8") as f:
            ranking = json.load(f)
        
        with open(self.backtest_path, "r", encoding="utf-8") as f:
            backtest = json.load(f)

        # Truncate ranking to top 5 for brevity
        top_ranking = ranking[:5]
        
        prompt = (
            "我们构建了一套面向跨领域技术趋势预测的自研 Agent 系统，结合了学术论文、开源社区、新闻报道等跨领域多源信号，"
            "并采用了‘相对注意力份额’与‘指数移动平均/MACD动量’结合的综合评分模型，执行了严格无未来数据泄露的滚动时间窗口回测。\n\n"
            "【最新一期技术预测榜单（Top 5）】：\n"
            f"{json.dumps(top_ranking, ensure_ascii=False, indent=2)}\n\n"
            "【历史滚动回测结果（包含 1 个月前瞻与 3 个月前瞻两个时间尺度，覆盖 Top-1 Lift、Spearman 秩相关系数、NDCG@3、NDCG@5 等排序指标）】：\n"
            f"{json.dumps(backtest, ensure_ascii=False, indent=2)}\n\n"
            "请基于上述实验数据，撰写一份结构严谨、具备学术和商业价值的实验结论与趋势研判报告。报告应包含以下核心板块：\n"
            "1. **核心前沿技术榜单深度解读**：\n"
            "   - 详细分析领跑技术（如机器人、AI智能体、大模型、具身智能等）的表现；\n"
            "   - 重点剖析‘相对注意力份额 (Relative Share)’与‘绝对活跃度’之间的关系，指出哪些技术属于稳健领跑，哪些技术处于份额加速扩张的黑马阶段。\n"
            "2. **多步长回测有效性与排序可靠性评估**：\n"
            "   - 对比 1 个月短期前瞻与 3 个月中长期前瞻的表现差异；\n"
            "   - 结合平均 Spearman 秩相关系数（排序单调性）以及 NDCG@3 / NDCG@5（头部前瞻命中增益）评估系统的稳定度和可信度；\n"
            "   - 总结模型在历史主要技术爆发期（如 LLM 爆发周期）的表现规律。\n"
            "3. **研判结论与后续行动建议**：\n"
            "   - 为科研人员提供最具前沿突破潜力的交叉方向建议；\n"
            "   - 为产业投资者提供中长期技术配置节奏建议；\n"
            "   - 对预测 Agent 模型的下一步改进方向提出工程建议。\n\n"
            "请使用清晰的专业中文、Markdown 格式化表格与排版，保持客观严谨的科研基调。"
        )

        import asyncio
        print("Calling DeepSeek API...")
        report_md = asyncio.run(self._call_deepseek(prompt))

        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.report_path, "w", encoding="utf-8") as f:
            f.write(report_md)
        
        print(f"Report saved to {self.report_path}")
