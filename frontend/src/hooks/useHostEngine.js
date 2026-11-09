import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import api from "@/lib/api";
import { AGENT_URL, applyQuality, gamePath, getIce, keepAliveSocket, preferCodecs, signalUrl } from "@/lib/stream";

async function audioDeviceTrack(name) {
  const tmp = await navigator.mediaDevices.getUserMedia({ audio: true });
  tmp.getTracks().forEach((t) => t.stop());
  const dev = (await navigator.mediaDevices.enumerateDevices())
    .find((d) => d.kind === "audioinput" && d.label.toLowerCase().includes(name.toLowerCase()));
  if (!dev) return null;
  const s = await navigator.mediaDevices.getUserMedia({
    audio: { deviceId: { exact: dev.deviceId }, echoCancellation: false, noiseSuppression: false, autoGainControl: false },
  });
  return s.getAudioTracks()[0];
}

// Everything the PC host does: capture, local agent bridge, one RTCPeerConnection per viewer
export default function useHostEngine() {
  const [agent, setAgent] = useState({ state: "off" }); // off | connecting | ok | badpin
  const [capturing, setCapturing] = useState(false);
  const [signal, setSignal] = useState("off");
  const [viewers, setViewers] = useState([]);
  const [turn, setTurn] = useState("");
  const [log, setLog] = useState([]);

  const agentWs = useRef(null);
  const sig = useRef(null);
  const stream = useRef(null);
  const peers = useRef(new Map());
  const ice = useRef(null);
  const lib = useRef({ games: [] });
  const previewRef = useRef(null);

  const note = useCallback((m) => setLog((l) => [`${new Date().toLocaleTimeString()} · ${m}`, ...l].slice(0, 30)), []);
  const refreshViewers = () => setViewers([...peers.current.entries()].map(([id, p]) => ({ id, state: p.state, rtt: p.rtt, relay: p.relay })));

  const toAgent = (msg) => {
    if (agentWs.current?.readyState === 1) agentWs.current.send(JSON.stringify(msg));
  };
  const toViewers = (msg) => peers.current.forEach((p) => p.dc?.readyState === "open" && p.dc.send(JSON.stringify(msg)));

  const agentPin = useRef(null);
  const agentRetry = useRef(null);
  const agentOk = useRef(false);

  const connectAgent = useCallback((pin) => {
    clearTimeout(agentRetry.current);
    agentPin.current = pin;
    const old = agentWs.current;
    agentWs.current = null;
    try { old?.close(); } catch { /* noop */ }
    setAgent((a) => (a.state === "ok" ? a : { state: "connecting" }));
    let opened = false;
    let bad = false;
    const ws = new WebSocket(AGENT_URL);
    agentWs.current = ws;
    ws.onopen = () => { opened = true; ws.send(JSON.stringify({ pin })); };
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.t === "auth") {
        if (m.ok) {
          localStorage.setItem("vx_agent_pin", pin);
          agentOk.current = true;
          setAgent({ state: "ok", gamepad: m.gamepad, platform: m.platform, sunshine: m.sunshine });
          note("Agente local conectado");
          toViewers({ t: "agent", ok: true });
        } else { bad = true; agentPin.current = null; setAgent({ state: "badpin" }); }
      } else if (m.t === "sunshine-result") {
        if (m.ok) { toast.success(`Sunshine sincronizado: ${m.added} novo(s), ${m.updated} atualizado(s)`); note("Sunshine sincronizado"); }
        else toast.error(m.error);
      } else if (m.t === "status") {
        note(m.text);
        toViewers(m);
      }
    };
    ws.onclose = () => {
      if (agentWs.current !== ws) return;
      if (bad) return;
      if (!opened) note("Sem acesso ao agente: confira se ele está aberto e permita \"Acesso à rede local\" no cadeado do Chrome");
      setAgent({ state: "off" });
      if (agentOk.current) { agentOk.current = false; toViewers({ t: "agent", ok: false }); }
      if (agentPin.current) agentRetry.current = setTimeout(() => agentPin.current && connectAgent(agentPin.current), 2000);
    };
  }, [note]);

  const syncSunshine = useCallback(async () => {
    if (agentWs.current?.readyState !== 1) return toast.error("Pareie o agente do PC primeiro");
    const { data } = await api.get("/mygames/sunshine/export");
    toAgent({ t: "sunshine-sync", apps: data.apps });
    toast.info(`Enviando ${data.apps.length} jogo(s) para o Sunshine…`);
  }, []);

  const launchGame = useCallback((id, gameId) => {
    const p = peers.current.get(id);
    const reply = (text) => p?.dc?.readyState === "open" && p.dc.send(JSON.stringify({ t: "status", state: "error", text }));
    const g = lib.current.games.find((x) => x.id === gameId);
    if (!g) return reply("Jogo não encontrado");
    if (agentWs.current?.readyState !== 1) return reply("Agente do PC desconectado");
    note(`Abrindo ${g.title}`);
    toAgent({ t: "launch", game_id: g.id, title: g.title, path: gamePath(g), args: g.args });
  }, [note]);

  const handleViewerMsg = useCallback((id, m) => {
    const p = peers.current.get(id);
    if (m.t === "quality" && p?.videoSender) {
      applyQuality(p.videoSender, m.preset);
      note(`Qualidade alterada: ${m.preset}`);
    } else if (m.t !== "launch") {
      toAgent(m);
    }
  }, [note]);

  const closePeer = (id) => {
    const p = peers.current.get(id);
    if (!p) return;
    clearTimeout(p.dropTimer);
    try { p.pc.close(); } catch { /* noop */ }
    peers.current.delete(id);
    toAgent({ t: "release" });
    if (!peers.current.size) toAgent({ t: "viewers-empty" });
    refreshViewers();
  };

  const createPeer = useCallback(async (id, force = false) => {
    if (!stream.current) return;
    const old = peers.current.get(id);
    if (old && !force && ["connected", "connecting", "new"].includes(old.pc.connectionState)) return;
    closePeer(id);
    toAgent({ t: "viewer-joined" });
    const pc = new RTCPeerConnection({ iceServers: ice.current.iceServers });
    const entry = { pc, dc: null, videoSender: null, state: "conectando", pending: [], dropTimer: null };
    peers.current.set(id, entry);
    const s = stream.current;
    s.getVideoTracks().forEach((t) => {
      const tr = pc.addTransceiver(t, { direction: "sendonly", streams: [s] });
      preferCodecs(tr);
      entry.videoSender = tr.sender;
    });
    s.getAudioTracks().forEach((t) => pc.addTrack(t, s));
    const dc = pc.createDataChannel("input", { ordered: true });
    dc.onopen = () => dc.send(JSON.stringify({ t: "agent", ok: agentWs.current?.readyState === 1 }));
    dc.onmessage = (e) => handleViewerMsg(id, JSON.parse(e.data));
    entry.dc = dc;
    // fast lane for controller state: no retransmits, no head-of-line blocking (viewer resends state every 100ms)
    const pad = pc.createDataChannel("pad", { ordered: false, maxRetransmits: 0 });
    pad.onmessage = (e) => toAgent(JSON.parse(e.data));
    pc.onicecandidate = (e) => e.candidate && sig.current?.send({ type: "ice", to: id, candidate: e.candidate });
    pc.onconnectionstatechange = () => {
      if (peers.current.get(id) !== entry) return;
      entry.state = pc.connectionState;
      clearTimeout(entry.dropTimer);
      if (pc.connectionState === "connected") note(`Dispositivo ${id} conectado`);
      if (pc.connectionState === "failed" || pc.connectionState === "closed") { note(`Conexão com ${id} caiu`); closePeer(id); return; }
      if (pc.connectionState === "disconnected") entry.dropTimer = setTimeout(() => pc.connectionState !== "connected" && closePeer(id), 20000);
      refreshViewers();
    };
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    await applyQuality(entry.videoSender, "high");
    sig.current?.send({ type: "offer", to: id, sdp: pc.localDescription });
    refreshViewers();
  }, [handleViewerMsg, note]);

  const connectSignal = useCallback(() => {
    setSignal("connecting");
    sig.current = keepAliveSocket(() => signalUrl("host"), {
      onDown: () => setSignal((s) => (s === "replaced" ? s : "connecting")),
      onMessage: async (m) => {
        if (m.type === "welcome") { setSignal("online"); m.viewers.forEach((id) => createPeer(id)); }
        else if (m.type === "viewer-joined") { note(`Dispositivo: ${m.id}`); createPeer(m.id); }
        else if (m.type === "viewer-left") {
          const p = peers.current.get(m.id);
          if (p && p.pc.connectionState !== "connected") closePeer(m.id);
        } else if (m.type === "rejoin") createPeer(m.from, true);
        else if (m.type === "launch") launchGame(m.from, m.game_id);
        else if (m.type === "quit") { note("Jogador saiu do jogo"); toAgent({ t: "quit" }); }
        else if (m.type === "replaced") { note("Outra aba assumiu como host"); setSignal("replaced"); sig.current?.close(); }
        else if (m.type === "answer") {
          const p = peers.current.get(m.from);
          if (p) {
            await p.pc.setRemoteDescription(m.sdp);
            for (const c of p.pending) await p.pc.addIceCandidate(c).catch(() => {});
            p.pending = [];
          }
        } else if (m.type === "ice") {
          const p = peers.current.get(m.from);
          if (!p) return;
          if (p.pc.remoteDescription) await p.pc.addIceCandidate(m.candidate).catch(() => {});
          else p.pending.push(m.candidate);
        }
      },
    });
  }, [createPeer, launchGame, note]);

  const stopCapture = useCallback(() => {
    [...peers.current.keys()].forEach(closePeer);
    sig.current?.close();
    sig.current = null;
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    setCapturing(false);
    setSignal("off");
  }, []);

  const startCapture = useCallback(async ({ audio = "" } = {}) => {
    const [iceData, games] = await Promise.all([getIce(), api.get("/mygames")]);
    ice.current = iceData;
    lib.current = { games: games.data };
    setTurn(iceData.turn);
    const s = await navigator.mediaDevices.getDisplayMedia({
      video: { frameRate: { ideal: 60, max: 60 }, width: { ideal: 1920 }, height: { ideal: 1080 } },
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
      systemAudio: "include",
      selfBrowserSurface: "exclude",
    });
    if (audio && !s.getAudioTracks().length) {
      const t = await audioDeviceTrack(audio).catch(() => null);
      if (t) s.addTrack(t);
    }
    s.getVideoTracks().forEach((t) => { t.contentHint = "motion"; t.onended = () => { note("Captura encerrada"); stopCapture(); }; });
    stream.current = s;
    setCapturing(true);
    note(`Captura iniciada${s.getAudioTracks().length ? " (com áudio)" : " (sem áudio)"}`);
    connectSignal();
  }, [connectSignal, note, stopCapture]);

  // viewer latency stats
  useEffect(() => {
    const t = setInterval(async () => {
      for (const p of peers.current.values()) {
        try {
          const r = await p.pc.getStats();
          r.forEach((s) => {
            if (s.type === "candidate-pair" && s.nominated && s.state === "succeeded") {
              p.rtt = Math.round((s.currentRoundTripTime || 0) * 1000);
              p.relay = r.get(s.localCandidateId)?.candidateType === "relay";
            }
          });
        } catch { /* closed */ }
      }
      if (peers.current.size) refreshViewers();
    }, 2000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => () => {
    stopCapture();
    agentPin.current = null;
    clearTimeout(agentRetry.current);
    try { agentWs.current?.close(); } catch { /* noop */ }
  }, [stopCapture]);

  return { agent, capturing, signal, viewers, turn, log, previewRef, stream, connectAgent, startCapture, stopCapture, syncSunshine };
}
