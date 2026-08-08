# Edge Agent installation

1. Install Docker Engine, Docker Compose and `v4l-utils` on the customer host.
2. Copy `deploy/customer/docker-compose.yml`, `mediamtx.yml` and `.env.example`
   to a private deployment directory.
3. Provision a tenant and device through the control-plane bootstrap endpoint.
   Store the returned device credential only in the customer `.env` file.
4. Create the MQTT TLS CA file at `deploy/customer/secrets/ca.crt`.
5. Set `EDGE_CAMERA_SOURCES` as a JSON mapping, for example:

   ```dotenv
   EDGE_CAMERA_SOURCES={"cam-1":"/dev/video0"}
   ```

6. Start the local stack with `docker compose up -d`.

The Edge Agent opens outbound HTTPS/RTSP/MQTT connections only. The frontend
continues to use the local backend and does not receive SaaS credentials.

