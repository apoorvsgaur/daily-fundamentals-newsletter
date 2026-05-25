import json
import os
import smtplib
import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import yfinance as yf
import feedparser
import requests
from jinja2 import Template

CONFIG_PATH = Path(__file__).parent / "config.json"
REPORT_DIR = Path(__file__).parent / "report"

BUTTONDOWN_API_KEY = os.environ.get("BUTTONDOWN_API_KEY", "")
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
GMAIL_SENDER = os.environ.get("GMAIL_SENDER", "")
TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"
TEST_RECIPIENT = "apoorvsgaur@gmail.com"

PAGES_URL = "https://apoorvsgaur.github.io/daily-fundamentals-newsletter"


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def fetch_market_data(watchlist):
    tickers = yf.Tickers(" ".join(watchlist))
    results = []
    for symbol in watchlist:
        try:
            t = tickers.tickers[symbol]
            info = t.info
            hist = t.history(period="2d")
            if len(hist) < 2:
                continue
            prev_close = hist["Close"].iloc[-2]
            last_close = hist["Close"].iloc[-1]
            change_pct = ((last_close - prev_close) / prev_close) * 100
            results.append({
                "symbol": symbol,
                "price": last_close,
                "change_pct": change_pct,
                "pe_ratio": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "market_cap": info.get("marketCap"),
                "sector": info.get("sector", "ETF/Index"),
                "earnings_date": info.get("earningsTimestamp"),
                "recommendation": info.get("recommendationKey"),
                "target_price": info.get("targetMeanPrice"),
            })
        except Exception:
            continue
    return results


def fetch_rss_news():
    feeds = [
        ("Reuters Business", "https://www.reutersagency.com/feed/?taxonomy=best-sectors&post_type=best"),
        ("CNBC Economy", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258"),
        ("MarketWatch", "https://feeds.marketwatch.com/marketwatch/topstories/"),
        ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
    ]
    articles = []
    for name, url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                articles.append({
                    "source": name,
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "published": entry.get("published", ""),
                    "summary": entry.get("summary", "")[:200],
                })
        except Exception:
            continue
    return articles


def fetch_fred_data(series_ids):
    if not FRED_API_KEY:
        return {}
    try:
        from fredapi import Fred
        fred = Fred(api_key=FRED_API_KEY)
        results = {}
        labels = {
            "DFF": "Fed Funds Rate",
            "T10Y2Y": "10Y-2Y Spread",
            "T10YIE": "10Y Breakeven Inflation",
            "UNRATE": "Unemployment Rate",
            "CPIAUCSL": "CPI (All Urban)",
            "GDP": "GDP",
            "UMCSENT": "Consumer Sentiment",
        }
        for sid in series_ids:
            try:
                data = fred.get_series(sid, observation_start=datetime.date.today() - datetime.timedelta(days=90))
                if len(data) > 0:
                    latest = data.dropna().iloc[-1]
                    results[labels.get(sid, sid)] = f"{latest:.2f}"
            except Exception:
                continue
        return results
    except Exception:
        return {}


def build_web_report(market_data, news, macro_data, date_str):
    template = Template("""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Daily Fundamentals Report — {{ date_str }}</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, 'Segoe UI', Arial, sans-serif; background: #f4f4f7; color: #1a1a2e; line-height: 1.5; }
  .container { max-width: 800px; margin: 0 auto; padding: 20px; }
  .header { background: #1a1a2e; color: #fff; padding: 32px; border-radius: 12px 12px 0 0; }
  .header h1 { font-size: 26px; font-family: Georgia, serif; margin-bottom: 4px; }
  .header p { color: #a0a0b0; font-size: 14px; }
  .content { background: #fff; border-radius: 0 0 12px 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.06); }

  .section { border-bottom: 1px solid #eee; }
  .section:last-child { border-bottom: none; }
  .section-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 18px 32px; cursor: pointer; user-select: none;
    transition: background 0.15s;
  }
  .section-header:hover { background: #f8f9fa; }
  .section-header h2 { font-size: 15px; text-transform: uppercase; letter-spacing: 0.5px; color: #1a1a2e; }
  .section-header .arrow { font-size: 18px; color: #999; transition: transform 0.25s; }
  .section-header.open .arrow { transform: rotate(180deg); }
  .section-body { padding: 0 32px 24px 32px; display: none; }
  .section-body.open { display: block; }

  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th { text-align: left; padding: 10px 12px; background: #f8f9fa; color: #555; font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.3px; border-bottom: 2px solid #e0e0e0; }
  td { padding: 9px 12px; border-bottom: 1px solid #f0f0f0; }
  tr:last-child td { border-bottom: none; }
  tr:hover { background: #fafbfc; }
  .ticker { font-weight: 700; }
  .up { color: #16a34a; font-weight: 600; }
  .down { color: #dc2626; font-weight: 600; }
  .macro-label { font-weight: 600; }

  .news-item { padding: 12px 0; border-bottom: 1px solid #f0f0f0; }
  .news-item:last-child { border-bottom: none; }
  .news-item a { color: #1a1a2e; text-decoration: none; font-size: 15px; line-height: 1.4; }
  .news-item a:hover { text-decoration: underline; color: #2563eb; }
  .news-meta { color: #999; font-size: 12px; margin-top: 4px; }

  .footer { text-align: center; padding: 24px; color: #999; font-size: 12px; }

  @media (max-width: 600px) {
    .container { padding: 10px; }
    .header, .section-header, .section-body { padding-left: 16px; padding-right: 16px; }
    th, td { padding: 7px 6px; font-size: 12px; }
  }
</style>
</head>
<body>
<div class="container">

<div class="header">
  <h1>Daily Fundamentals Report</h1>
  <p>{{ date_str }}</p>
</div>

<div class="content">

  <div class="section">
    <div class="section-header open" onclick="toggle(this)">
      <h2>Market Overview</h2>
      <span class="arrow">&#9660;</span>
    </div>
    <div class="section-body open">
      <table>
      <tr>
        <th>Ticker</th>
        <th>Price</th>
        <th>Change</th>
        <th>P/E</th>
        <th>Fwd P/E</th>
        <th>Sector</th>
      </tr>
      {% for stock in market_data %}
      <tr>
        <td class="ticker">{{ stock.symbol }}</td>
        <td>${{ "%.2f"|format(stock.price) }}</td>
        <td class="{{ 'up' if stock.change_pct >= 0 else 'down' }}">{{ "%+.2f"|format(stock.change_pct) }}%</td>
        <td>{{ "%.1f"|format(stock.pe_ratio) if stock.pe_ratio else "—" }}</td>
        <td>{{ "%.1f"|format(stock.forward_pe) if stock.forward_pe else "—" }}</td>
        <td>{{ stock.sector }}</td>
      </tr>
      {% endfor %}
      </table>
    </div>
  </div>

  {% if macro_data %}
  <div class="section">
    <div class="section-header" onclick="toggle(this)">
      <h2>Macro Indicators</h2>
      <span class="arrow">&#9660;</span>
    </div>
    <div class="section-body">
      <table>
      <tr><th>Indicator</th><th>Latest Value</th></tr>
      {% for name, value in macro_data.items() %}
      <tr>
        <td class="macro-label">{{ name }}</td>
        <td>{{ value }}</td>
      </tr>
      {% endfor %}
      </table>
    </div>
  </div>
  {% endif %}

  <div class="section">
    <div class="section-header" onclick="toggle(this)">
      <h2>Financial News</h2>
      <span class="arrow">&#9660;</span>
    </div>
    <div class="section-body">
      {% for article in news[:15] %}
      <div class="news-item">
        <a href="{{ article.link }}" target="_blank">{{ article.title }}</a>
        <div class="news-meta">{{ article.source }} &middot; {{ article.published }}</div>
      </div>
      {% endfor %}
    </div>
  </div>

</div>

<div class="footer">
  Data from Yahoo Finance, FRED, and public RSS feeds. Generated automatically.
</div>

</div>
<script>
function toggle(header) {
  header.classList.toggle('open');
  var body = header.nextElementSibling;
  body.classList.toggle('open');
}
</script>
</body>
</html>
""")
    return template.render(
        market_data=market_data,
        news=news,
        macro_data=macro_data,
        date_str=date_str,
    )


def build_summary_email(market_data, news, macro_data, date_str, report_url):
    top_movers = sorted(market_data, key=lambda x: abs(x["change_pct"]), reverse=True)[:5]
    indices = [s for s in market_data if s["symbol"] in ("SPY", "QQQ", "DIA", "IWM")]

    template = Template("""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body { margin: 0; padding: 0; background-color: #f4f4f7; }
  .wrapper { width: 100%; background-color: #f4f4f7; padding: 30px 0; }
  .container { max-width: 620px; margin: 0 auto; background: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
  .header { background: #1a1a2e; padding: 24px 30px; }
  .header h1 { color: #ffffff; margin: 0; font-size: 22px; font-family: Georgia, serif; }
  .header p { color: #a0a0b0; margin: 6px 0 0 0; font-size: 13px; font-family: Arial, sans-serif; }
  .section { padding: 20px 30px; border-bottom: 1px solid #eee; font-family: Arial, sans-serif; }
  .section:last-child { border-bottom: none; }
  .section h2 { color: #1a1a2e; font-size: 14px; margin: 0 0 12px 0; text-transform: uppercase; letter-spacing: 0.5px; }
  table.data { width: 100%; border-collapse: collapse; font-size: 13px; }
  table.data th { text-align: left; padding: 8px 10px; background: #f8f9fa; color: #555; font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.3px; border-bottom: 2px solid #e0e0e0; }
  table.data td { padding: 7px 10px; border-bottom: 1px solid #f0f0f0; }
  .ticker { font-weight: 700; color: #1a1a2e; }
  .up { color: #16a34a; font-weight: 600; }
  .down { color: #dc2626; font-weight: 600; }
  .cta { text-align: center; padding: 24px 30px; }
  .cta a {
    display: inline-block; padding: 14px 32px;
    background: #1a1a2e; color: #ffffff; text-decoration: none;
    border-radius: 6px; font-size: 15px; font-weight: 600;
    font-family: Arial, sans-serif;
  }
  .footer { padding: 16px 30px; text-align: center; color: #999; font-size: 11px; font-family: Arial, sans-serif; }
</style>
</head>
<body>
<div class="wrapper">
<div class="container">

<div class="header">
  <h1>Daily Fundamentals Report</h1>
  <p>{{ date_str }}</p>
</div>

<div class="section">
  <h2>Index Snapshot</h2>
  <table class="data">
  <tr><th>Index</th><th>Price</th><th>Change</th></tr>
  {% for idx in indices %}
  <tr>
    <td class="ticker">{{ idx.symbol }}</td>
    <td>${{ "%.2f"|format(idx.price) }}</td>
    <td class="{{ 'up' if idx.change_pct >= 0 else 'down' }}">{{ "%+.2f"|format(idx.change_pct) }}%</td>
  </tr>
  {% endfor %}
  </table>
</div>

<div class="section">
  <h2>Top Movers</h2>
  <table class="data">
  <tr><th>Ticker</th><th>Price</th><th>Change</th></tr>
  {% for stock in top_movers %}
  <tr>
    <td class="ticker">{{ stock.symbol }}</td>
    <td>${{ "%.2f"|format(stock.price) }}</td>
    <td class="{{ 'up' if stock.change_pct >= 0 else 'down' }}">{{ "%+.2f"|format(stock.change_pct) }}%</td>
  </tr>
  {% endfor %}
  </table>
</div>

{% if macro_highlights %}
<div class="section">
  <h2>Key Macro Numbers</h2>
  <table class="data">
  {% for name, value in macro_highlights %}
  <tr>
    <td style="font-weight: 600;">{{ name }}</td>
    <td>{{ value }}</td>
  </tr>
  {% endfor %}
  </table>
</div>
{% endif %}

<div class="cta">
  <a href="{{ report_url }}">View Full Interactive Report &rarr;</a>
</div>

<div class="footer">
  Data from Yahoo Finance, FRED, and public RSS feeds. Generated automatically.
</div>

</div>
</div>
</body>
</html>
""")
    macro_highlights = list(macro_data.items())[:3] if macro_data else []
    return template.render(
        indices=indices,
        top_movers=top_movers,
        macro_highlights=macro_highlights,
        date_str=date_str,
        report_url=report_url,
    )


def get_subscribers():
    subscribers = []
    url = "https://api.buttondown.com/v1/subscribers"
    headers = {"Authorization": f"Token {BUTTONDOWN_API_KEY}"}
    while url:
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        for sub in data["results"]:
            if sub.get("subscriber_type", "regular") == "regular":
                subscribers.append(sub["email_address"])
        url = data.get("next")
    return subscribers


def send_email(subject, html_body, recipients):
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(GMAIL_SENDER, GMAIL_APP_PASSWORD)
        for recipient in recipients:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = GMAIL_SENDER
            msg["To"] = recipient
            msg.attach(MIMEText(html_body, "html"))
            server.sendmail(GMAIL_SENDER, recipient, msg.as_string())
            print(f"  Sent to {recipient}")


def main():
    config = load_config()
    date_str = datetime.date.today().strftime("%A, %B %d, %Y")
    date_slug = datetime.date.today().strftime("%Y-%m-%d")

    print(f"[{datetime.datetime.now()}] Fetching market data...")
    market_data = fetch_market_data(config["watchlist"])

    print(f"[{datetime.datetime.now()}] Fetching news...")
    news = fetch_rss_news()

    print(f"[{datetime.datetime.now()}] Fetching macro data...")
    macro_data = fetch_fred_data(config.get("fred_series", []))

    print(f"[{datetime.datetime.now()}] Building web report...")
    web_html = build_web_report(market_data, news, macro_data, date_str)
    REPORT_DIR.mkdir(exist_ok=True)
    report_path = REPORT_DIR / "index.html"
    report_path.write_text(web_html, encoding="utf-8")
    print(f"  Written to {report_path}")

    report_url = PAGES_URL
    print(f"[{datetime.datetime.now()}] Building summary email...")
    email_html = build_summary_email(market_data, news, macro_data, date_str, report_url)

    if TEST_MODE:
        subscribers = [TEST_RECIPIENT]
        print(f"[{datetime.datetime.now()}] TEST MODE — sending only to {TEST_RECIPIENT}")
    else:
        print(f"[{datetime.datetime.now()}] Fetching subscriber list from Buttondown...")
        subscribers = get_subscribers()
        extra = config.get("extra_subscribers", [])
        subscribers = list(set(subscribers + extra))
        print(f"  Found {len(subscribers)} subscriber(s)")

    subject = f"Daily Fundamentals Report — {date_str}"
    if TEST_MODE:
        subject = f"[TEST] {subject}"
    print(f"[{datetime.datetime.now()}] Sending via Gmail SMTP...")
    send_email(subject, email_html, subscribers)
    print(f"[{datetime.datetime.now()}] Done!")


if __name__ == "__main__":
    main()
