import React, { useEffect, useRef } from "react";
import useHostEngine from "@/hooks/useHostEngine";

// Opened by the PC agent in a dedicated Chrome window: captures automatically and serves viewers
export default function HostAuto() {
  const h = useHostEngine();
  const started = useRef(false);
  const { connectAgent, startCapture } = h;

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    document.title = "Vortex Host";
    const q = new URLSearchParams(window.location.search);
    if (q.get("token")) localStorage.setItem("vx_token", q.get("token"));
    window.history.replaceState(null, "", "/host-auto");
    if (q.get("pin")) connectAgent(q.get("pin"));
    startCapture({ audio: q.get("audio") || "" }).catch(() => {});
  }, [connectAgent, startCapture]);

  return (
    <div className="min-h-screen bg-[#0E1012] p-4 font-mono-vx text-xs text-slate-300" data-testid="host-auto-page">
      <p className="text-sm font-bold text-cyan-400" data-testid="host-auto-state">
        Vortex Host · {h.capturing ? "transmitindo" : "iniciando"} · {h.viewers.length} jogador(es)
      </p>
      {h.log.slice(0, 6).map((l, i) => <p key={i}>{l}</p>)}
    </div>
  );
}
