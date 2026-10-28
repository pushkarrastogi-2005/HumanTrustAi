import base64
import cloudinary
import cloudinary.uploader
import cloudinary.utils
from fastapi.concurrency import run_in_threadpool

cloudinary.config(secure=True)  # reads CLOUDINARY_URL from the environment


def _upload(image_b64: str, session_id: str, pid: str, ts: int) -> dict:
    res = cloudinary.uploader.upload(
        base64.b64decode(image_b64),
        folder="humantrust-evidence",
        public_id=f"{session_id}_{pid}_{ts}",
        type="authenticated",          # not publicly viewable
        resource_type="image",
        tags=["humantrust", session_id],
    )
    # Authenticated assets need a signed link
    url, _ = cloudinary.utils.cloudinary_url(
        res["public_id"], type="authenticated", sign_url=True, secure=True
    )
    return {"public_id": res["public_id"], "url": url}


async def upload_frame(image_b64: str, session_id: str, pid: str, ts: int) -> dict:
    # The Cloudinary SDK is blocking, so run it in a thread
    return await run_in_threadpool(_upload, image_b64, session_id, pid, ts)
