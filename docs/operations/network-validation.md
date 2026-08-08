# Network validation spike

Before cutover, run one real customer camera through the customer MediaMTX
and cloud MediaMTX ingress for 24 hours. Record:

- camera-to-edge, edge-to-ingress and ingress-to-worker timestamps;
- end-to-end event latency;
- upload bitrate per 1280x720@25 FPS camera;
- reconnect count and continuous outage duration;
- worker dropped-frame count.

Run the same test with a throttled/unstable network profile. Do not change
model thresholds or preprocessing to hide network problems. A network change
must be handled by transport/reconnect policy or explicitly approved as a
quality-impacting change.

