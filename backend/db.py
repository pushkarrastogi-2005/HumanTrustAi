from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGODB_URI, DB_NAME

client = AsyncIOMotorClient(MONGODB_URI)
db = client[DB_NAME]

sessions = db.sessions   # one document per meeting
scores = db.scores       # one document per check, per participant
alerts = db.alerts       # only moderate or suspicious checks
