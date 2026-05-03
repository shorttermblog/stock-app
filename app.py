from datetime import date, timedelta
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import yfinance as yf
import feedparser
from urllib.parse import quote

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def home():
    return FileResponse("static/index.html")


# 🔹 funzione per Google News RSS
def get_google_news(ticker: str, company_name: str = "", max_news: int = 5):
    query = f'"{ticker}" "{company_name}" stock OR earnings when:1d'
    encoded_query = quote(query)

    url = (
        f"https://news.google.com/rss/search?"
        f"q={encoded_query}"
        f"&hl=en-US&gl=US&ceid=US:en"
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

        last = float(data["Close"].iloc[-1])
        prev = float(data["Close"].iloc[-2])

        change = last - prev
        change_pct = (change / prev) * 100

        prices = [
            {
                "date": str(row["Date"])[:10],
                "close": float(row["Close"])
            }
            for _, row in data.iterrows()
        ]

        # 🔹 nome azienda (per migliorare news)
        try:
            company_name = stock.info.get("shortName", "")
        except:
            company_name = ""

        # 🔹 news da Google
        news_list = get_google_news(ticker.upper(), company_name)

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
