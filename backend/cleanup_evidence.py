import cloudinary
import cloudinary.api
import cloudinary.search
from dotenv import load_dotenv

load_dotenv()
cloudinary.config(secure=True)

res = (cloudinary.search.Search()
       .expression("folder:humantrust-evidence AND created_at<7d")
       .max_results(100).execute())
ids = [r["public_id"] for r in res["resources"]]
if ids:
    cloudinary.api.delete_resources(ids, type="authenticated")
print(f"Deleted {len(ids)} evidence files")
