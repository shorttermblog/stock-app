from datetime import date, timedelta
from urllib.parse import quote
import os

import feedparser
import pandas as pd
import requests
import yfinance as yf

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from openai import OpenAI


app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def home():
    return FileResponse("static/index.html")


# OpenAI client
# Make sure you set OPENAI_API_KEY in your environment.
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


ALLOWED_QUOTE_TYPES = {
    "EQUITY",
    "ETF",
    "FUTURE",
    "CURRENCY",
    "INDEX",
    "CRYPTOCURRENCY",
    "MUTUALFUND",
}


class NewsSummaryRequest(BaseModel):
    ticker: str
    asset_name: str
    quote_type: str = ""
    news: list


@app.get("/api/search")
def search_assets(q: str):
    """
    Returns Yahoo Finance-like suggestions for stocks, ETFs, futures,
    currencies, indices, crypto, and mutual funds.
    """

    query = q.strip()

    if not query:
        return {"results": []}

    url = "https://query2.finance.yahoo.com/v1/finance/search"

    params = {
        "q": query,
        "quotes_count": 12,
        "news_count": 0,
    }

    headers = {
        "User-Agent": "Mozilla/5.0",
    }

    try:
        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=10,
        )

        response.raise_for_status()

        yahoo_results = response.json().get("quotes", [])

        results = []

        for item in yahoo_results:
            symbol = item.get("symbol", "")
            quote_type = item.get("quoteType", "")

            if not symbol:
                continue

            if quote_type not in ALLOWED_QUOTE_TYPES:
                continue

            name = (
                item.get("shortname")
                or item.get("longname")
                or item.get("name")
                or symbol
            )

            results.append(
                {
                    "symbol": symbol,
                    "name": name,
                    "quote_type": quote_type,
                    "exchange": item.get("exchange", ""),
                    "exchange_name": item.get("exchDisp", ""),
                    "type_display": item.get("typeDisp", ""),
                }
            )

        return {"results": results}

    except requests.exceptions.RequestException:
        return {"results": []}


def resolve_stock_symbol(query: str):
    """
    Accepts a company name, ticker, ETF, index, future, currency,
    cryptocurrency, or mutual fund name.

    Examples:
    - Apple -> AAPL
    - Tesla -> TSLA
    - QQQ -> QQQ
    - S&P 500 -> ^GSPC
    - Bitcoin USD -> BTC-USD
    - gold futures -> GC=F
    - crude oil futures -> CL=F
    - euro dollar -> EURUSD=X

    If Yahoo search fails, it falls back to treating the input as a direct symbol.
    """

    query = query.strip()

    if not query:
        return {
            "symbol": "",
            "company_name": "",
            "quote_type": "",
        }

    url = "https://query2.finance.yahoo.com/v1/finance/search"

    params = {
        "q": query,
        "quotes_count": 10,
        "news_count": 0,
    }

    headers = {
        "User-Agent": "Mozilla/5.0",
    }

    try:
        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=10,
        )

        response.raise_for_status()

        results = response.json().get("quotes", [])

        for item in results:
            quote_type = item.get("quoteType", "")
            symbol = item.get("symbol", "")

            short_name = (
                item.get("shortname")
                or item.get("longname")
                or item.get("name")
                or ""
            )

            if symbol and quote_type in ALLOWED_QUOTE_TYPES:
                return {
                    "symbol": symbol,
                    "company_name": short_name,
                    "quote_type": quote_type,
                }

    except requests.exceptions.RequestException:
        pass

    return {
        "symbol": query.upper(),
        "company_name": "",
        "quote_type": "",
    }


def get_google_news(
    symbol: str,
    company_name: str = "",
    quote_type: str = "",
    max_news: int = 10,
):
    """
    Builds a news query depending on the instrument type.
    Uses OR between symbol and company name so the search is less restrictive.
    """

    symbol = symbol.strip()
    company_name = company_name.strip()

    if company_name:
        asset_query = f'("{symbol}" OR "{company_name}")'
    else:
        asset_query = f'"{symbol}"'

    if quote_type in {
        "ETF",
        "FUTURE",
        "CURRENCY",
        "INDEX",
        "CRYPTOCURRENCY",
        "MUTUALFUND",
    }:
        search_query = (
            f"{asset_query} "
            f"market OR price OR forecast OR inflation OR rates OR fund OR ETF when:7d"
        )
    else:
        search_query = (
            f"{asset_query} "
            f"stock OR earnings OR shares OR revenue when:7d"
        )

    encoded_query = quote(search_query)

    url = (
        "https://news.google.com/rss/search?"
        f"q={encoded_query}&hl=en-US&gl=US&ceid=US:en"
    )

    feed = feedparser.parse(url)

    news_list = []

    for entry in feed.entries[:max_news]:
        news_list.append(
            {
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "published": entry.get("published", ""),
                "source": entry.get("source", {}).get("title", ""),
            }
        )

    return news_list


def summarize_news_with_chatgpt(
    ticker: str,
    asset_name: str,
    quote_type: str,
    news_list: list,
):
    """
    Uses ChatGPT to summarize recent news related to the selected ticker.
    The summary is based only on the news titles, sources, and publication dates.
    """

    if not news_list:
        return "No recent news available for this asset."

    if not os.getenv("OPENAI_API_KEY"):
        return "News summary unavailable because OPENAI_API_KEY is not configured."

    news_text = "\n".join(
        [
            f"- Title: {item.get('title', '')}\n"
            f"  Source: {item.get('source', '')}\n"
            f"  Published: {item.get('published', '')}"
            for item in news_list
        ]
    )

    prompt = f"""
You are a financial news analyst.

Summarize the recent news for this asset.

Ticker: {ticker}
Asset name: {asset_name}
Quote type: {quote_type}

News items:
{news_text}

Instructions:
- Use only the provided news headlines, sources, and publication dates.
- Do not invent facts.
- Do not give investment advice.
- Focus on what the headlines suggest is currently driving attention around the asset.
- Mention earnings, revenue, macro, rates, commodities, crypto, sector trends, regulation, or analyst coverage only if they appear in the provided headlines.
- Organize the summary as bullet points.
- Keep the summary under 150 words.
- Write in clear English.
"""

    try:
        response = client.responses.create(
            model="gpt-4.1-mini",
            input=prompt,
        )

        return response.output_text.strip()

    except Exception:
        return "News summary unavailable right now."


@app.post("/api/news-summary")
def generate_news_summary(payload: NewsSummaryRequest):
    """
    Generates a ChatGPT news summary only when called explicitly,
    for example when the user clicks a frontend button.
    """

    summary = summarize_news_with_chatgpt(
        ticker=payload.ticker,
        asset_name=payload.asset_name,
        quote_type=payload.quote_type,
        news_list=payload.news,
    )

    return {
        "news_summary": summary,
    }


@app.get("/api/stock")
def get_stock(ticker: str, start: str = None, end: str = None):
    try:
        resolved = resolve_stock_symbol(ticker)

        symbol = resolved["symbol"]
        resolved_company_name = resolved["company_name"]
        quote_type = resolved["quote_type"]

        if not symbol:
            return {
                "error": "Inserisci un nome valido, ad esempio Apple, Tesla, gold futures, Bitcoin USD o euro dollar."
            }

        stock = yf.Ticker(symbol)

        # ------------------------------------------------------------
        # Date handling
        # ------------------------------------------------------------
        # If the user does not pass start/end, use Yahoo's period-based
        # daily historical data. This is closer to Yahoo Finance's own
        # historical daily view and can include the latest available
        # daily candle during the session.
        #
        # If the user passes custom dates, use start/end, but add one day
        # to end because yfinance treats end as exclusive.
        # ------------------------------------------------------------

        if start is None and end is None:
            data = stock.history(
                period="2y",
                interval="1d",
                auto_adjust=False,
            )

        else:
            end_date = date.today() if not end else date.fromisoformat(end)

            start_date = (
                end_date - timedelta(days=365 * 2)
                if not start
                else date.fromisoformat(start)
            )

            if start_date >= end_date:
                return {
                    "error": "La data iniziale deve essere precedente alla data finale."
                }

            data = stock.history(
                start=start_date,
                end=end_date + timedelta(days=1),
                interval="1d",
                auto_adjust=False,
            )

        if data.empty or len(data) < 2:
            return {
                "error": "Strumento non valido o pochi dati disponibili."
            }

        data = data.reset_index()

        data["MA20"] = data["Close"].rolling(window=20).mean()
        data["STD20"] = data["Close"].rolling(window=20).std()
        data["BB_UPPER"] = data["MA20"] + (2 * data["STD20"])
        data["BB_LOWER"] = data["MA20"] - (2 * data["STD20"])

        last = float(data["Close"].iloc[-1])
        prev = float(data["Close"].iloc[-2])

        change = last - prev
        change_pct = (change / prev) * 100

        prices = []

        for _, row in data.iterrows():
            prices.append(
                {
                    "date": str(row["Date"])[:10],
                    "open": round(float(row["Open"]), 2),
                    "high": round(float(row["High"]), 2),
                    "low": round(float(row["Low"]), 2),
                    "close": round(float(row["Close"]), 2),
                    "ma20": None
                    if pd.isna(row["MA20"])
                    else round(float(row["MA20"]), 2),
                    "bb_upper": None
                    if pd.isna(row["BB_UPPER"])
                    else round(float(row["BB_UPPER"]), 2),
                    "bb_lower": None
                    if pd.isna(row["BB_LOWER"])
                    else round(float(row["BB_LOWER"]), 2),
                }
            )

        try:
            company_name = stock.info.get("shortName", "") or resolved_company_name
        except Exception:
            company_name = resolved_company_name

        asset_name = company_name or resolved_company_name or symbol

        news_list = get_google_news(
            symbol=symbol,
            company_name=asset_name,
            quote_type=quote_type,
            max_news=10,
        )

        return {
            "query": ticker,
            "ticker": symbol,
            "asset_name": asset_name,
            "company_name": company_name,
            "quote_type": quote_type,
            "price": round(last, 2),
            "change": round(change, 2),
            "change_pct": round(change_pct, 2),
            "prices": prices,
            "news": news_list,
            "news_summary": None,
        }

    except ValueError:
        return {
            "error": "Formato data non valido. Usa YYYY-MM-DD."
        }

    except Exception:
        return {
            "error": "Unable to load asset data right now. Please try again later."
        }
