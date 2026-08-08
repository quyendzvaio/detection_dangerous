# SaaS Edge Architecture

The customer host owns local user authentication, the local database and the
frontend. It publishes camera input outbound through MediaMTX. The SaaS
control plane authenticates devices, stores tenant/stream metadata, and the
inference worker reads only tenant-scoped RTSP paths from MediaMTX.

```text
camera -> edge-agent -> MediaMTX Edge ==RTSP/TLS outbound==> MediaMTX SaaS
                                                   -> inference-worker -> Triton
                                                   -> MQTT QoS 0 -> customer consumer
                                                   -> object storage signed URL
```

MQTT topics are `events/{tenant}/{device}/{camera}`,
`config/{tenant}/{device}/{camera}` and `status/{tenant}/{device}`. The event
payload remains the existing SafetyEvent payload and is wrapped in a transport
envelope containing identity and idempotency metadata.

The current local backend/auth deployment remains compatible during migration;
the `run_inference_worker.sh --media-mtx-only` entrypoint is the explicit
server-side mode and rejects non-RTSP sources.

