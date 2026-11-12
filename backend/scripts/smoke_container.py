"""Test a built image as its nonroot user, including photo/database persistence.

Usage: python backend/scripts/smoke_container.py [image]
Creates an isolated temporary Docker volume; SYNTHETIC records never enter city data.
"""
import io
import os
import secrets
import subprocess
import sys
import tempfile
import time
import uuid

import httpx
from PIL import Image

image = sys.argv[1] if len(sys.argv) > 1 else "burdasaxla-admin-test"
name = "burdasaxla-smoke-" + uuid.uuid4().hex[:10]
volume = name + "-data"
docker = ["docker", "--host=unix:///var/run/docker.sock"]


def run(*args):
    return subprocess.check_output([*docker, *args], text=True).strip()


try:
    run("volume", "create", volume)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env") as env:
        token = secrets.token_urlsafe(32)
        env.write("BURDASAXLA_ADMIN_TOKEN=" + token + "\n")
        env.flush()
        os.chmod(env.name, 0o600)
        run("run", "-d", "--name", name, "--env-file", env.name, "-p", "127.0.0.1::8000", "-v", volume + ":/data", image)
    host = run("port", name, "8000/tcp")
    with httpx.Client(base_url="http://" + host, headers={"X-Admin-Token": token}, timeout=15) as client:
        def ready():
            for _ in range(60):
                try:
                    response = client.get("/api/health")
                    if response.status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                time.sleep(0.5)
            print(run("logs", "--tail", "60", name))
            raise RuntimeError("Container did not become healthy")

        ready()
        assert run("exec", name, "id", "-u") == "10001"
        response = client.post("/api/admin/features", json={
            "kind": "sign_3_28", "geometry": {"type": "Point", "coordinates": [49.85, 40.38]},
            "source": "field_survey", "source_ref": "SYNTHETIC CONTAINER TEST ONLY",
            "observer": "SYNTHETIC TEST", "observed_at": "2020-01-01", "status": "pending"})
        response.raise_for_status()
        fid = response.json()["id"]
        buf = io.BytesIO()
        Image.new("RGB", (16, 16), "purple").save(buf, "JPEG")
        response = client.post(f"/api/admin/features/{fid}/evidence",
                               files={"file": ("synthetic.jpg", buf.getvalue(), "image/jpeg")})
        response.raise_for_status()
        filename = response.json()["evidence"]["filename"]
        assert filename in run("exec", name, "ls", "/data/evidence")
        run("restart", name)
        client.base_url = "http://" + run("port", name, "8000/tcp")
        ready()
        response = client.get(f"/api/admin/features/{fid}")
        response.raise_for_status()
        assert response.json()["evidence"][0]["filename"] == filename
        assert filename in run("exec", name, "ls", "/data/evidence")
        assert client.get("/").status_code == 200
    print("PASS: nonroot container startup, authenticated admin create/upload, database and photo persistence after restart")
finally:
    subprocess.run([*docker, "rm", "-f", name], capture_output=True)
    subprocess.run([*docker, "volume", "rm", volume], capture_output=True)
