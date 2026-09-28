import re
import random
import logging
import asyncio
from dataclasses import dataclass
from typing import List, Optional, Tuple
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger("telegram_focus.scraper")

@dataclass
class ScrapedPage:
    url: str
    title: str = ""
    content: str = ""
    status_code: int = 0
    is_success: bool = False
    fallback_needed: bool = False
    error_reason: Optional[str] = None
    extracted_deadline: Optional[str] = None

class ResilientWebScraper:
    USER_AGENTS = [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ]

    def __init__(self, timeout_seconds: int = 6, max_chars: int = 2000):
        self.timeout = timeout_seconds
        self.max_chars = max_chars

    def _clean_html(self, html: str) -> Tuple[str, str, Optional[str]]:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "form", "svg"]):
            tag.decompose()
        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        text = " ".join(soup.stripped_strings)
        clean_text = re.sub(r"\s+", " ", text)[:self.max_chars]
        deadline = None
        match = re.search(r'(?:deadline|muddati|apply before)[\s:]+([0-9]{1,2}[\/\-\.][0-9]{1,2}[\/\-\.][0-9]{2,4}|\d{4}-\d{2}-\d{2})', clean_text, re.I)
        if match:
            deadline = match.group(1)
        return title, clean_text, deadline

    async def scrape_url(self, url: str) -> ScrapedPage:
        if "t.me/" in url:
            return ScrapedPage(url=url, title="Telegram Link", is_success=True, content="Telegram ichki havolasi.")
        headers = {"User-Agent": random.choice(self.USER_AGENTS)}
        try:
            async with httpx.AsyncClient(headers=headers, timeout=float(self.timeout), follow_redirects=True) as client:
                res = await client.get(url)
                if res.status_code in (401, 403):
                    return ScrapedPage(url=url, status_code=res.status_code, fallback_needed=True, content="Sayt himoya ostida (403/Cloudflare).")
                title, clean_text, deadline = self._clean_html(res.text or "")
                return ScrapedPage(url=url, title=title, content=clean_text, status_code=res.status_code, is_success=True, extracted_deadline=deadline)
        except Exception as e:
            return ScrapedPage(url=url, fallback_needed=True, error_reason=str(e), content="Havola yuklanmadi, post matniga tayanildi.")

    async def scrape_multiple_urls(self, urls: List[str]) -> List[ScrapedPage]:
        if not urls:
            return []
        tasks = [self.scrape_url(u) for u in urls[:2]]
        return await asyncio.gather(*tasks)

web_scraper = ResilientWebScraper()
