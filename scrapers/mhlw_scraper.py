"""
MHLW 介護サービス情報公表システム scraper.
Source: https://www.kaigokensaku.mhlw.go.jp/

Scrapes care facility data for Tokyo's 23 wards and saves to data/raw/.
Each facility record includes: name, address, ward, services, capacity, contact.
"""

import asyncio
import json
from typing import Optional
import re
import time
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from config.settings import get_settings

console = Console()
settings = get_settings()

RAW_DATA_DIR = Path("data/raw")
RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)

# MHLW care service search endpoint (Tokyo = prefecture 13)
SEARCH_URL = f"{settings.mhlw_base_url}/{settings.tokyo_pref_code}/index.php"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.9",
}

# Minimum delay between requests (be polite to public servers)
REQUEST_DELAY_SEC = 1.5


def _parse_facility_from_row(row: BeautifulSoup, service_code: str) -> Optional[dict]:
    """Parse a single facility row from search results HTML."""
    try:
        cells = row.find_all("td")
        if len(cells) < 3:
            return None

        name_tag = cells[0].find("a") or cells[0]
        name = name_tag.get_text(strip=True)
        if not name:
            return None

        address_text = cells[1].get_text(strip=True) if len(cells) > 1 else ""
        phone = cells[2].get_text(strip=True) if len(cells) > 2 else ""

        # Extract ward from address (look for 区)
        ward_match = re.search(r"([\u4e00-\u9fff]+区)", address_text)
        ward = ward_match.group(1) if ward_match else "不明"

        return {
            "name": name,
            "address": address_text,
            "ward": ward,
            "phone": phone,
            "service_code": service_code,
            "service_name": settings.service_type_codes.get(service_code, ""),
            "prefecture": "東京都",
            "source": "MHLW介護サービス情報公表システム",
        }
    except Exception:
        return None


def _parse_search_results(html: str, service_code: str) -> list[dict]:
    """Extract facility records from a search results page."""
    soup = BeautifulSoup(html, "html.parser")
    facilities = []

    # The results table varies slightly by page version — try multiple selectors
    table = (
        soup.find("table", {"class": re.compile(r"result|search|list", re.I)})
        or soup.find("table", {"id": re.compile(r"result|list", re.I)})
        or soup.find("table")
    )

    if not table:
        return facilities

    for row in table.find_all("tr")[1:]:  # skip header
        facility = _parse_facility_from_row(row, service_code)
        if facility:
            facilities.append(facility)

    return facilities


async def _fetch_page(
    client: httpx.AsyncClient,
    service_code: str,
    page: int = 1,
) -> Optional[str]:
    """Fetch one page of search results for a given service type."""
    params = {
        "action_kouhyou_search_index_2": "true",
        "PrefCd": settings.tokyo_pref_code,
        "ServiceKindCd": service_code,
        "page": str(page),
        "dispCount": "50",
    }
    try:
        resp = await client.get(SEARCH_URL, params=params, timeout=20)
        resp.raise_for_status()
        return resp.text
    except httpx.HTTPStatusError as e:
        console.print(f"[yellow]HTTP {e.response.status_code} for service {service_code} p{page}[/yellow]")
        return None
    except Exception as e:
        console.print(f"[red]Fetch error: {e}[/red]")
        return None


async def scrape_service_type(
    client: httpx.AsyncClient,
    service_code: str,
    max_pages: int = 5,
) -> list[dict]:
    """Scrape all pages for one service type and return facility records."""
    all_facilities = []
    service_name = settings.service_type_codes.get(service_code, service_code)

    for page in range(1, max_pages + 1):
        html = await _fetch_page(client, service_code, page)
        if not html:
            break

        facilities = _parse_search_results(html, service_code)
        if not facilities:
            break  # no more results

        all_facilities.extend(facilities)
        console.print(
            f"  [green]{service_name}[/green] page {page}: "
            f"{len(facilities)} facilities (total: {len(all_facilities)})"
        )

        await asyncio.sleep(REQUEST_DELAY_SEC)

    return all_facilities


async def run_scraper(service_codes: Optional[list] = None) -> list:
    """
    Main scraper entry point.
    Scrapes MHLW for all (or specified) service types in Tokyo.
    Saves results to data/raw/mhlw_tokyo.json.
    """
    codes = service_codes or list(settings.service_type_codes.keys())
    all_facilities: list[dict] = []

    console.rule("[bold blue]MHLW 介護サービス情報公表システム Scraper[/bold blue]")
    console.print(f"Target: Tokyo (都道府県コード {settings.tokyo_pref_code})")
    console.print(f"Service types: {len(codes)}")

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True) as client:
        for code in codes:
            name = settings.service_type_codes.get(code, code)
            console.print(f"\n[bold]Scraping:[/bold] {name} (code={code})")
            facilities = await scrape_service_type(client, code)
            all_facilities.extend(facilities)

    # Deduplicate by (name, address)
    seen = set()
    unique: list[dict] = []
    for f in all_facilities:
        key = (f["name"], f["address"])
        if key not in seen:
            seen.add(key)
            unique.append(f)

    # Save raw
    out_path = RAW_DATA_DIR / "mhlw_tokyo.json"
    out_path.write_text(json.dumps(unique, ensure_ascii=False, indent=2), encoding="utf-8")

    console.print(
        f"\n[bold green]Done.[/bold green] "
        f"{len(unique)} unique facilities saved to {out_path}"
    )
    return unique


def load_or_generate_sample_data() -> list[dict]:
    """
    Return sample data for testing when the live scraper hasn't been run.
    Covers all 9 service types across multiple Tokyo wards.
    """
    return [
        {
            "name": "世田谷ケアサービスセンター",
            "address": "東京都世田谷区三軒茶屋2-1-1",
            "ward": "世田谷区",
            "phone": "03-1234-5678",
            "service_code": "11",
            "service_name": "訪問介護 (Home Visit Care)",
            "capacity": 40,
            "operating_hours": "8:00-18:00",
            "prefecture": "東京都",
            "source": "sample",
            "description_en": "Home visit care service in Setagaya ward. Provides daily living assistance, bathing support, and personal care for elderly residents.",
            "description_jp": "世田谷区の訪問介護サービス。入浴介助、身体介護、生活援助を提供。",
        },
        {
            "name": "新宿訪問看護ステーション",
            "address": "東京都新宿区西新宿4-5-2",
            "ward": "新宿区",
            "phone": "03-2345-6789",
            "service_code": "13",
            "service_name": "訪問看護 (Home Visit Nursing)",
            "capacity": 30,
            "operating_hours": "9:00-17:00",
            "prefecture": "東京都",
            "source": "sample",
            "description_en": "Home visit nursing in Shinjuku ward. Provides medical nursing care, medication management, and health monitoring.",
            "description_jp": "新宿区の訪問看護サービス。医療的ケア、服薬管理、健康観察を提供。",
        },
        {
            "name": "渋谷デイサービスセンター",
            "address": "東京都渋谷区代々木1-10-3",
            "ward": "渋谷区",
            "phone": "03-3456-7890",
            "service_code": "21",
            "service_name": "通所介護 (Day Service)",
            "capacity": 25,
            "operating_hours": "9:00-16:00",
            "prefecture": "東京都",
            "source": "sample",
            "description_en": "Day service center in Shibuya ward. Provides social activities, rehabilitation exercises, and daily care for elderly.",
            "description_jp": "渋谷区のデイサービスセンター。機能訓練、社会交流、日常生活援助を提供。",
        },
        {
            "name": "港区特別養護老人ホーム ゆうき園",
            "address": "東京都港区芝浦3-4-5",
            "ward": "港区",
            "phone": "03-4567-8901",
            "service_code": "41",
            "service_name": "特別養護老人ホーム (Special Nursing Home)",
            "capacity": 100,
            "operating_hours": "24時間",
            "prefecture": "東京都",
            "source": "sample",
            "description_en": "Special nursing home in Minato ward. Full-time residential care for elderly with care level 3 and above. 100-bed facility.",
            "description_jp": "港区の特別養護老人ホーム。要介護3以上の方を対象とした100床の入所施設。",
        },
        {
            "name": "豊島区訪問リハビリテーション",
            "address": "東京都豊島区池袋2-3-4",
            "ward": "豊島区",
            "phone": "03-5678-9012",
            "service_code": "14",
            "service_name": "訪問リハビリ (Home Visit Rehabilitation)",
            "capacity": 20,
            "operating_hours": "9:00-18:00",
            "prefecture": "東京都",
            "source": "sample",
            "description_en": "Home visit rehabilitation in Toshima ward. Physical and occupational therapy for post-hospitalization recovery.",
            "description_jp": "豊島区の訪問リハビリ。退院後の在宅回復支援、理学療法・作業療法を提供。",
        },
        {
            "name": "江東区短期入所生活介護 さくら",
            "address": "東京都江東区亀戸1-5-6",
            "ward": "江東区",
            "phone": "03-6789-0123",
            "service_code": "31",
            "service_name": "短期入所生活介護 (Short-Stay Care)",
            "capacity": 30,
            "operating_hours": "随時受付",
            "prefecture": "東京都",
            "source": "sample",
            "description_en": "Short-stay care (respite) in Koto ward. Temporary residential care for caregiver relief. Accepts emergency bookings.",
            "description_jp": "江東区のショートステイ。介護者の休息のための短期入所。緊急対応可能。",
        },
        {
            "name": "大田区介護老人保健施設 おおた",
            "address": "東京都大田区蒲田3-7-8",
            "ward": "大田区",
            "phone": "03-7890-1234",
            "service_code": "42",
            "service_name": "介護老人保健施設 (Care Health Facility)",
            "capacity": 80,
            "operating_hours": "24時間",
            "prefecture": "東京都",
            "source": "sample",
            "description_en": "Care health facility in Ota ward. Post-hospital rehabilitation and nursing care. 80-bed facility with on-site doctors.",
            "description_jp": "大田区の介護老人保健施設。入院後の在宅復帰を目的とした80床施設。医師常駐。",
        },
        {
            "name": "杉並区通所リハビリテーション",
            "address": "東京都杉並区荻窪4-2-3",
            "ward": "杉並区",
            "phone": "03-8901-2345",
            "service_code": "22",
            "service_name": "通所リハビリ (Day Rehabilitation)",
            "capacity": 35,
            "operating_hours": "9:00-17:00",
            "prefecture": "東京都",
            "source": "sample",
            "description_en": "Day rehabilitation in Suginami ward. Group and individual therapy sessions. Specializes in stroke and hip fracture recovery.",
            "description_jp": "杉並区の通所リハビリ。脳卒中・骨折後の回復に特化したリハビリ提供。",
        },
        {
            "name": "文京区訪問入浴介護サービス",
            "address": "東京都文京区本郷5-1-2",
            "ward": "文京区",
            "phone": "03-9012-3456",
            "service_code": "12",
            "service_name": "訪問入浴介護 (Home Visit Bathing)",
            "capacity": 15,
            "operating_hours": "9:00-16:00",
            "prefecture": "東京都",
            "source": "sample",
            "description_en": "Home visit bathing service in Bunkyo ward. Mobile bathing unit visits home. Suitable for bedridden patients.",
            "description_jp": "文京区の訪問入浴介護。寝たきりの方への自宅入浴サービス。専用浴槽持参。",
        },
    ]


if __name__ == "__main__":
    asyncio.run(run_scraper())
