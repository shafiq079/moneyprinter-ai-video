"""Facebook view of the shared reviewed publishing queue.

YouTube jobs without a platform field remain YouTube; Facebook never adopts them.
"""

import json

from app.services import scene_planner, youtube_studio as delivery
from app.services.facebook_publisher import publisher

_ACTIVE = delivery._ACTIVE
completed_videos = delivery.completed_videos
source_file = delivery.source_file
snapshot_file = delivery.snapshot_file
scheduled_utc = delivery.scheduled_utc
recover = delivery.recover


def jobs():
    return delivery.jobs("facebook")


def get(job_id):
    job = delivery.get(job_id)
    if job.get("platform") != "facebook":
        raise ValueError("This delivery belongs to another platform.")
    return job


def prepare(task_id, relative, profile, page_id, value):
    return delivery.prepare(
        task_id, relative, profile, value, platform="facebook", page_id=page_id
    )


def approve(job_id, *, reviewed=False):
    get(job_id)
    return delivery.approve(job_id, reviewed=reviewed)


def refresh(job_id):
    get(job_id)
    return delivery.refresh(job_id)


def cancel(job_id):
    get(job_id)
    return delivery.cancel(job_id)


def retry(job_id, *, reviewed=False):
    get(job_id)
    return delivery.retry(job_id, reviewed=reviewed)


def cached_channels():
    target = delivery.root() / "facebook_channels.json"
    if (
        target.is_file()
        and not target.is_symlink()
        and target.stat().st_size <= 1024 * 1024
    ):
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            if data.get("credential_id") == publisher.credential_id:
                return data
        except (ValueError, AttributeError):
            pass
    return {"channels": [], "checked_at": None}


def refresh_channels():
    client = delivery._client(platform="facebook")
    data = {
        "credential_id": client.credential_id,
        "channels": client.profiles(),
        "checked_at": delivery._stamp(),
    }
    scene_planner._atomic_write_json(delivery.root() / "facebook_channels.json", data)
    return data


def assert_account_editable(profile):
    delivery.assert_account_editable(profile, platform="facebook")
