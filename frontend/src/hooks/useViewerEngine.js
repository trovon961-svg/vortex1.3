import { useCallback, useEffect, useRef, useState } from "react";
import { getIce, keepAliveSocket, readStats, signalUrl } from "@/lib/stream";

// Viewer side: receives the PC stream and sends input over a DataChannel
export default function useViewerEngine({ onHostMsg }) {
  const [phase, setPhase] = useState("connecting"); // connecting | no-host | negotiating | live | failed
  const [stats, setStats] = useState(null);
  const videoRef = useRef(null);
  const pc = useRef(null);
  const dc = useRef(null);
  const padDc = useRef(null);
  const sock = useRef(null);
  const pending = useRef([]);
  const hostMsg = useRef(onHostMsg);
  hostMsg.current = onHostMsg;

  const send = useCallback((m) => {
    const ch = m.t === "gp" && padDc.current?.readyState === "open" ? padDc.current : dc.current;
    if (ch?.readyState === "open") ch.send(JSON.stringify(m));
  }, []);
  const sendSig = useCallback((o) => sock.current?.send(o), []);

  useEffect(() => {
    let alive = true;
    let ice;
    let retries = 0;
    let dropTimer = null;
    const connected = () => pc.current?.connectionState === "connected";
    const resetPeer = () => {
      try { pc.current?.close(); } catch { /* noop */ }
      pc.current = null;
      dc.current = null;
      padDc.current = null;
      pending.current = [];
    };
    const sig = (o) => sock.current?.send(o);
    const recover = () => {
      if (!alive) return;
      if (retries++ >= 4) return setPhase("failed");
      setPhase("negotiating");
      resetPeer();
      sig({ type: "rejoin" });
    };

    const onOffer = async (sdp) => {
      const wasLive = connected();
      resetPeer();
      if (!wasLive) setPhase("negotiating");
      const p = new RTCPeerConnection({ iceServers: ice.iceServers });
      pc.current = p;
      p.ontrack = (e) => {
        try { e.receiver.jitterBufferTarget = 0; } catch { /* noop */ }
        try { e.receiver.playoutDelayHint = 0; } catch { /* noop */ }
        const v = videoRef.current;
        if (v && v.srcObject !== e.streams[0]) {
          v.srcObject = e.streams[0];
          v.play?.().catch(() => {});
        }
      };
      p.ondatachannel = (e) => {
        if (e.channel.label === "pad") { padDc.current = e.channel; return; }
        dc.current = e.channel;
        e.channel.onmessage = (ev) => hostMsg.current?.(JSON.parse(ev.data));
        e.channel.onopen = () => hostMsg.current?.({ t: "channel-open" });
      };
      p.onicecandidate = (e) => e.candidate && sig({ type: "ice", candidate: e.candidate });
      p.onconnectionstatechange = () => {
        if (pc.current !== p) return;
        clearTimeout(dropTimer);
        if (p.connectionState === "connected") { retries = 0; setPhase("live"); }
        if (p.connectionState === "failed") recover();
        if (p.connectionState === "disconnected") dropTimer = setTimeout(() => p.connectionState !== "connected" && recover(), 8000);
      };
      await p.setRemoteDescription(sdp);
      for (const c of pending.current) await p.addIceCandidate(c).catch(() => {});
      pending.current = [];
      const ans = await p.createAnswer();
      await p.setLocalDescription(ans);
      sig({ type: "answer", sdp: p.localDescription });
    };

    (async () => {
      ice = await getIce();
      if (!alive) return;
      sock.current = keepAliveSocket(() => signalUrl("viewer"), {
        onMessage: async (m) => {
          if (m.type === "welcome") {
            if (!connected()) setPhase(m.host ? "negotiating" : "no-host");
            hostMsg.current?.({ t: "welcome", host: m.host, agent: m.agent });
          } else if (m.type === "host-offline") {
            if (!connected()) { resetPeer(); setPhase("no-host"); }
          } else if (m.type === "host-online") { if (!connected()) setPhase("negotiating"); }
          else if (m.type === "agent-online" || m.type === "agent-offline") hostMsg.current?.({ t: m.type });
          else if (m.type === "status") hostMsg.current?.({ t: "status", state: m.state, text: m.text });
          else if (m.type === "offer") onOffer(m.sdp);
          else if (m.type === "ice") {
            if (pc.current?.remoteDescription) await pc.current.addIceCandidate(m.candidate).catch(() => {});
            else pending.current.push(m.candidate);
          }
        },
      });
    })().catch(() => setPhase("failed"));

    return () => {
      alive = false;
      clearTimeout(dropTimer);
      resetPeer();
      sock.current?.close();
    };
  }, []);

  useEffect(() => {
    if (phase !== "live") return undefined;
    let snap = null;
    const t = setInterval(async () => {
      if (!pc.current) return;
      const r = await readStats(pc.current, snap);
      snap = r.snap;
      setStats(r.stats);
    }, 1000);
    return () => clearInterval(t);
  }, [phase]);

  return { phase, stats, videoRef, send, sendSig };
}
