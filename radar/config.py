"""Central configuration: sources, keywords, geography, alerting."""
import os
import sys
from pathlib import Path

def env(name: str, default: str = "") -> str:
    """Read an env var, treating empty as absent.

    CI passes unset secrets through as empty strings, and a bare
    os.environ.get(name, default) then returns "" instead of the default.
    That silently pointed the ntfy URL at "/topic" and dropped every alert.
    """
    value = os.environ.get(name)
    return value if value not in (None, "") else default


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
WEB_DIR = ROOT / "web"
DB_PATH = DATA_DIR / "radar.db"
LOG_PATH = DATA_DIR / "radar.log"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
HTTP_TIMEOUT = 25
MAX_WORKERS = 8

# ---------------------------------------------------------------- alerting
ALERT_PHONE = env("RADAR_ALERT_PHONE", "+14159335114")
# The daily verdict is binary: 0 = no genuine protest news, send nothing;
# 1 = there is news, send exactly ALERT_BURST messages carrying SITE_URL.
ALERT_BURST = int(env("RADAR_ALERT_BURST", "5"))
ALERT_BURST_DELAY = float(env("RADAR_ALERT_DELAY", "3"))
# Absolute ceiling per calendar day, counted across every scan and every event.
# Two scans a day plus several qualifying events must never exceed this.
ALERT_MAX_PER_DAY = int(env("RADAR_MAX_PER_DAY", "5"))
# Public dashboard the alert messages link to (set by deploy_vercel.sh).
SITE_URL = env("RADAR_SITE_URL", "")
# Score at/above which an item is "CONFIRMED" and triggers the SMS burst.
CONFIRM_THRESHOLD = int(env("RADAR_CONFIRM_THRESHOLD", "70"))
# Score at/above which an item is a "SIGNAL" — shown on the dashboard, no SMS.
SIGNAL_THRESHOLD = int(env("RADAR_SIGNAL_THRESHOLD", "30"))
# Twilio (optional). Real SMS; works with every device off.
TWILIO_SID = env("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = env("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = env("TWILIO_FROM_NUMBER", "")

# ntfy.sh push notifications. Free, no account. Anyone who knows the topic can
# read it, so it is treated as a secret and kept out of the repo.
NTFY_TOPIC = env("RADAR_NTFY_TOPIC", "")
NTFY_SERVER = env("RADAR_NTFY_SERVER", "https://ntfy.sh")

# iMessage only works on a Mac that is awake and signed in, so it is disabled
# by default when the scan runs anywhere else (e.g. GitHub Actions on Linux).
IMESSAGE_ENABLED = env("RADAR_IMESSAGE", "auto").lower() in ("1", "true", "yes", "on") \
    or (env("RADAR_IMESSAGE", "auto").lower() == "auto"
        and sys.platform == "darwin")

# The calendar day the message cap is counted against. Fixed to the user's own
# timezone so a UTC cloud runner does not roll over mid-afternoon in California.
ALERT_TIMEZONE = env("RADAR_TIMEZONE", "America/Los_Angeles")

# ---------------------------------------------------------------- vocabulary
# Terms that mark the *subject* as AI.
AI_TERMS = [
    "ai", "a.i.", "artificial intelligence", "agi", "superintelligence",
    "openai", "anthropic", "deepmind", "google deepmind", "meta ai", "xai",
    "nvidia", "scale ai", "sam altman", "chatgpt", "llm", "large language model",
    "machine learning", "generative ai", "genai", "frontier model", "data center",
    "datacenter", "automation", "algorithmic", "robotaxi", "waymo", "cruise",
    "self-driving", "driverless", "surveillance tech", "facial recognition",
]

# Terms that mark the *action* as a protest / collective action.
PROTEST_TERMS = [
    "protest", "protests", "protesting", "protester", "protesters", "rally",
    "march", "demonstration", "demonstrate", "picket", "picketing", "walkout",
    "strike", "sit-in", "sit in", "occupation", "occupy", "blockade", "vigil",
    "direct action", "civil disobedience", "die-in", "banner drop", "boycott",
    "mobilization", "mobilisation", "action alert", "take to the streets",
    "gather outside", "gathering outside", "speak out", "town hall", "counter-protest",
    "hunger strike", "encampment", "teach-in", "petition delivery", "rsvp",
]

# Terms that mark it as *anti*-AI in stance.
STANCE_TERMS = [
    "pause ai", "pauseai", "stop ai", "stopai", "stop the race", "stoptherace",
    "no ai", "anti-ai", "anti ai", "ai safety", "ai risk", "existential risk",
    "shut it down", "moratorium", "ban ai", "regulate ai", "human artists",
    "not my ai", "ai slop", "job losses", "layoffs", "displacement",
    "against ai", "resist ai", "ai accountability", "algorithmic justice",
    "data center moratorium", "no data center", "stop the machine",
]

# Strong-signal phrases: near-certain match, big score bump.
HIGH_SIGNAL_PHRASES = [
    "ai protest", "anti-ai protest", "protest against ai", "protest ai",
    "pauseai protest", "stopai protest", "ai safety protest", "rally against ai",
    "march against ai", "protest outside openai", "protest at openai",
    "protest outside anthropic", "protest at anthropic", "picket openai",
    "anti-ai rally", "anti-ai march", "ai protest sf", "protest ai data center",
]

# Terms that indicate the item is NOT a protest signal (noise suppression).
NEGATIVE_TERMS = [
    "stock", "earnings", "ipo", "funding round", "series a", "series b",
    "hiring", "job opening", "webinar", "coupon", "discount", "buy now",
    "how to use ai", "ai tools for", "best ai", "ai course", "prompt engineering",
]

# ---------------------------------------------------------------- geography
PRIORITY_GEO = {
    "sf_bay": [
        "san francisco", "sf ", " sf", "bay area", "oakland", "berkeley",
        "san jose", "palo alto", "mountain view", "menlo park", "sunnyvale",
        "silicon valley", "mission district", "soma", "civic center",
        "embarcadero", "market street", "san mateo", "santa clara", "fremont",
        "richmond ca", "hayward", "daly city", "1955 broadway", "pier 70",
    ],
    "la": [
        "los angeles", "la ", " la", "hollywood", "santa monica", "pasadena",
        "long beach", "burbank", "culver city", "downtown la", "dtla",
        "west hollywood", "venice beach", "glendale", "anaheim", "irvine",
        "orange county", "san diego", "sherman oaks", "studio city",
    ],
}

US_GEO = [
    "united states", "u.s.", "usa", "america", "american", "nationwide",
    "washington dc", "washington, d.c.", "capitol hill", "white house",
    # major metros
    "new york", "nyc", "manhattan", "brooklyn", "queens ny", "chelsea",
    "boston", "chicago", "seattle", "austin", "denver", "portland oregon",
    "atlanta", "miami", "philadelphia", "houston", "dallas", "phoenix",
    "detroit", "minneapolis", "st. louis", "kansas city", "nashville",
    "new orleans", "las vegas", "salt lake city", "albuquerque", "tucson",
    "sacramento", "fresno", "bakersfield", "birmingham", "charlotte",
    "raleigh", "richmond", "baltimore", "pittsburgh", "cleveland",
    "columbus", "cincinnati", "indianapolis", "milwaukee", "omaha",
    "oklahoma city", "tulsa", "little rock", "jackson mississippi",
    "louisville", "buffalo", "rochester", "hartford", "providence",
    "des moines", "boise", "spokane", "tacoma", "eugene", "anchorage",
    # states
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "north carolina",
    "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania",
    "rhode island", "south carolina", "south dakota", "tennessee", "texas",
    "utah", "vermont", "virginia", "washington state", "west virginia",
    "wisconsin", "wyoming",
]

# Locations that mean "not the US" — used to demote foreign items.
FOREIGN_GEO = [
    "london", "uk ", "united kingdom", "britain", "british", "england",
    "scotland", "wales", "manchester uk", "bletchley", "westminster",
    "parliament square", "paris", "france", "french", "berlin", "germany",
    "german", "munich", "brussels", "belgium", "amsterdam", "netherlands",
    "dutch", "dublin", "ireland", "sydney", "australia", "australian",
    "melbourne", "brisbane", "new zealand", "auckland", "india", "delhi",
    "mumbai", "bangalore", "tokyo", "japan", "japanese", "seoul", "korea",
    "beijing", "shanghai", "china", "chinese", "singapore", "hong kong",
    "taiwan", "stockholm", "sweden", "oslo", "norway", "copenhagen",
    "denmark", "helsinki", "finland", "madrid", "spain", "barcelona",
    "rome", "italy", "milan", "zurich", "switzerland", "geneva", "vienna",
    "austria", "warsaw", "poland", "prague", "czech", "lisbon", "portugal",
    "athens", "greece", "budapest", "hungary", "istanbul", "turkey",
    "tel aviv", "israel", "dubai", "brazil", "sao paulo", "mexico city",
    "buenos aires", "argentina", "chile", "bogota", "nairobi", "lagos",
    "cape town", "south africa", "moscow", "russia", "kyiv", "ukraine",
    # Canada — frequently mistaken for US in data-centre protest coverage
    "canada", "canadian", "toronto", "ottawa", "montreal", "vancouver",
    "calgary", "edmonton", "winnipeg", "halifax", "quebec", "ontario",
    "alberta", "manitoba", "saskatchewan", "british columbia",
    "nova scotia", "sturgeon county", "b.c.",
]

# ---------------------------------------------------------------- sources
# Direct HTML pages scraped for protest/event announcements.
SITE_SOURCES = [
    # --- dedicated anti-AI / AI-safety organizing ---
    {"name": "PauseAI — Protests", "url": "https://pauseai.info/protests", "tier": "core"},
    {"name": "PauseAI — Events", "url": "https://pauseai.info/events", "tier": "core"},
    {"name": "PauseAI — Blog", "url": "https://pauseai.info/posts", "tier": "core"},
    {"name": "PauseAI US", "url": "https://pauseai-us.org/", "tier": "core"},
    {"name": "PauseAI US — Take Action", "url": "https://pauseai-us.org/action", "tier": "core"},
    {"name": "StopAI", "url": "https://www.stopai.info/", "tier": "core"},
    {"name": "StopAI — Events", "url": "https://www.stopai.info/events", "tier": "core"},
    {"name": "StopAI — Take Action", "url": "https://www.stopai.info/take-action", "tier": "core"},
    {"name": "Stop The Race", "url": "https://stoptherace.ai/", "tier": "core"},
    {"name": "No AGI", "url": "https://www.noagi.org/", "tier": "core"},
    {"name": "Encode Justice", "url": "https://encodejustice.org/", "tier": "core"},
    {"name": "The Midas Project", "url": "https://www.themidasproject.com/", "tier": "core"},
    {"name": "AI Now Institute", "url": "https://ainowinstitute.org/news", "tier": "watch"},
    {"name": "Algorithmic Justice League", "url": "https://www.ajl.org/take-action", "tier": "watch"},
    {"name": "Tech Workers Coalition", "url": "https://techworkerscoalition.org/", "tier": "watch"},
    {"name": "Athena Coalition", "url": "https://athenaforall.org/", "tier": "watch"},
    # --- artist / labor anti-AI ---
    {"name": "Concept Art Association", "url": "https://www.conceptartassociation.com/", "tier": "watch"},
    {"name": "National Association of Voice Actors", "url": "https://www.navavoices.org/", "tier": "watch"},
    {"name": "SAG-AFTRA — News", "url": "https://www.sagaftra.org/news", "tier": "watch"},
    {"name": "Writers Guild West", "url": "https://www.wga.org/", "tier": "watch"},
    # --- grassroots / indymedia protest listings ---
    {"name": "Indybay — Calendar", "url": "https://www.indybay.org/calendar/", "tier": "core"},
    {"name": "Indybay — SF Bay Newswire", "url": "https://www.indybay.org/", "tier": "core"},
    {"name": "Indybay — Search 'AI'", "url": "https://www.indybay.org/search/?query=artificial+intelligence", "tier": "core"},
    {"name": "LA Indymedia", "url": "https://la.indymedia.org/", "tier": "watch"},
    {"name": "Bay Area Current (KPFA)", "url": "https://kpfa.org/area/news/", "tier": "watch"},
    {"name": "Mission Local", "url": "https://missionlocal.org/", "tier": "watch"},
    {"name": "48 Hills", "url": "https://48hills.org/", "tier": "watch"},
    {"name": "SF Standard", "url": "https://sfstandard.com/", "tier": "watch"},
    {"name": "LAist", "url": "https://laist.com/", "tier": "watch"},
    {"name": "Berkeleyside", "url": "https://www.berkeleyside.org/", "tier": "watch"},
]

# RSS / Atom feeds pulled directly.
RSS_SOURCES = [
    {"name": "Indybay — Newswire RSS",
     "url": "https://www.indybay.org/syn/generate_rss.php?news_item_status_restriction=1155"},
    {"name": "Indybay — Blurbs RSS",
     "url": "https://www.indybay.org/syn/generate_rss.php?include_blurbs=1&include_posts=0"},
    {"name": "Indybay — Calendar RSS",
     "url": "https://www.indybay.org/syn/generate_rss.php?page_id=12&include_posts=0&include_blurbs=1"},
    {"name": "PauseAI Substack", "url": "https://pauseai.substack.com/feed"},
    {"name": "Mission Local RSS", "url": "https://missionlocal.org/feed/"},
    {"name": "48 Hills RSS", "url": "https://48hills.org/feed/"},
    {"name": "SF Standard RSS", "url": "https://sfstandard.com/feed/"},
    {"name": "SFist RSS", "url": "https://sfist.com/feed/"},
    {"name": "LAist RSS", "url": "https://laist.com/index.rss"},
    {"name": "Berkeleyside RSS", "url": "https://www.berkeleyside.org/feed"},
    {"name": "Hoodline SF RSS", "url": "https://hoodline.com/rss/san-francisco.rss"},
    {"name": "El Tecolote RSS", "url": "https://eltecolote.org/content/en/feed/"},
    {"name": "Truthout RSS", "url": "https://truthout.org/latest/feed"},
    {"name": "Common Dreams RSS", "url": "https://www.commondreams.org/feeds/news.rss"},
    {"name": "The Intercept RSS", "url": "https://theintercept.com/feed/?rss"},
    {"name": "Labor Notes RSS", "url": "https://labornotes.org/feed"},
    {"name": "Waging Nonviolence RSS", "url": "https://wagingnonviolence.org/feed/"},
    {"name": "It's Going Down RSS", "url": "https://itsgoingdown.org/feed/"},
    {"name": "404 Media RSS", "url": "https://www.404media.co/rss/"},
    {"name": "Tech Policy Press RSS", "url": "https://techpolicy.press/feed"},
]

# Google News RSS queries — the highest-yield discovery channel.
NEWS_QUERIES = [
    '"AI protest"', '"anti-AI protest"', '"protest against AI"',
    '"AI protest" San Francisco', '"AI protest" Los Angeles',
    '"protest" "OpenAI" headquarters', '"protest" "Anthropic" office',
    'protest artificial intelligence rally', 'PauseAI protest', 'StopAI protest',
    '"anti-AI" rally OR march', 'protest "data center" AI California',
    'artists protest AI Los Angeles', 'workers protest AI automation US',
    'demonstration "artificial intelligence" San Francisco',
    'picket AI company San Francisco', '"AI" protest Silicon Valley',
    'protest Waymo OR robotaxi San Francisco', '"shut it down" AI protest',
    'AI moratorium rally United States',
]

# GDELT full-text queries (global news monitoring, US-filtered).
GDELT_QUERIES = [
    '"AI protest" sourcecountry:US',
    '("protest" OR "rally") "artificial intelligence" sourcecountry:US',
    '"anti-AI" (protest OR rally OR march) sourcecountry:US',
    '(PauseAI OR StopAI) sourcecountry:US',
    '"protest" (OpenAI OR Anthropic) sourcecountry:US',
]

# Reddit search feeds (via .rss — the JSON API blocks datacenter IPs).
REDDIT_QUERIES = [
    "AI protest san francisco", "anti-AI protest", "protest OpenAI",
    "protest Anthropic", "PauseAI", "StopAI protest", "AI rally los angeles",
    "protest artificial intelligence",
]
REDDIT_SUBS = [
    "sanfrancisco", "bayarea", "LosAngeles", "losangeles", "ControlProblem",
    "singularity", "ArtistHate", "aiwars", "antiai", "Futurology",
    "BayAreaEvents", "sfbayarea",
]

# Bluesky full-text search (unauthenticated public endpoint).
BLUESKY_QUERIES = [
    "AI protest", "anti-AI protest", "PauseAI", "StopAI", "protest OpenAI",
    "protest Anthropic", "AI protest San Francisco", "AI protest LA",
    "rally against AI", "march against AI",
]

# Mobilize.us — nationwide progressive event platform (public API).
MOBILIZE_QUERIES = ["artificial intelligence", "AI", "tech accountability", "data center"]

# Eventbrite / Luma public search pages.
EVENT_SEARCH_URLS = [
    {"name": "Eventbrite — SF AI protest",
     "url": "https://www.eventbrite.com/d/ca--san-francisco/ai-protest/"},
    {"name": "Eventbrite — LA AI protest",
     "url": "https://www.eventbrite.com/d/ca--los-angeles/ai-protest/"},
    {"name": "Eventbrite — SF protest",
     "url": "https://www.eventbrite.com/d/ca--san-francisco/protest/"},
    {"name": "Luma — SF",
     "url": "https://lu.ma/sf"},
]
