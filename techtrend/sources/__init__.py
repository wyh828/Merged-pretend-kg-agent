"""数据源客户端（P2：OpenAlex + arXiv + USPTO + GDELT + GitHub + RSSHub）。"""
from techtrend.sources.arxiv import ArxivClient
from techtrend.sources.gdelt import GdeltClient
from techtrend.sources.github import GithubClient
from techtrend.sources.openalex import OpenAlexClient
from techtrend.sources.rsshub import RssHubClient
from techtrend.sources.uspto import UsptoClient

__all__ = [
    "OpenAlexClient",
    "ArxivClient",
    "UsptoClient",
    "GdeltClient",
    "GithubClient",
    "RssHubClient",
]
