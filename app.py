from datetime import date, timedelta
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import yfinance as yf
import feedparser
from urllib.parse import quote
import pandas as pd

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def home():
    return FileResponse("static/index.html")


def get_google_news(ticker: str, company_name: str = "", max_news: int = 10):
    query = f'"{ticker}" "{company_name}" stock OR earnings OR shares OR revenue when:7d'
    encoded_query = quote(query)

    url = (
        "https://news.google.com/rss/search?"
        f"q={encoded_query}&hl=en-US&gl=US&ceid=US:en"
    )

    feed = feedparser.parse(url)

    news_list = []

    for entry in feed.entries[:max_news]:
        news_list.append({
            "title": entry.get("title", ""),
            "link": entry.get("link", ""),
            "published": entry.get("published", ""),
            "source": entry.get("source", {}).get("title", "")
        })

    return news_list


@app.get("/api/stock")
def get_stock(ticker: str, start: str = None, end: str = None):
    try:
        end_date = date.today() if not end else date.fromisoformat(end)
        start_date = end_date - timedelta(days=365 * 2) if not start else date.fromisoformat(start)

        stock = yf.Ticker(ticker.upper())
        data = stock.history(start=start_date, end=end_date)

        if data.empty or len(data) < 2:
            return {"error": "Ticker non valido o pochi dati"}

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
            prices.append({
                "date": str(row["Date"])[:10],
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "ma20": None if pd.isna(row["MA20"]) else round(float(row["MA20"]), 2),
                "bb_upper": None if pd.isna(row["BB_UPPER"]) else round(float(row["BB_UPPER"]), 2),
                "bb_lower": None if pd.isna(row["BB_LOWER"]) else round(float(row["BB_LOWER"]), 2),
            })

        try:
            company_name = stock.info.get("shortName", "")
        except:
            company_name = ""

        news_list = get_google_news(ticker.upper(), company_name, max_news=10)

        return {
            "ticker": ticker.upper(),
            "price": round(last, 2),
            "change": round(change, 2),
            "change_pct": round(change_pct, 2),
            "prices": prices,
            "news": news_list
        }

    except Exception as e:
        return {"error": str(e)}
