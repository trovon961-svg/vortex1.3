import React, { useCallback, useEffect, useRef } from "react";

const BIT = { A: 0, B: 1, X: 2, Y: 3, LB: 4, RB: 5, BACK: 8, START: 9, LS: 10, RS: 11, UP: 12, DOWN: 13, LEFT: 14, RIGHT: 15, GUIDE: 16 };
const FACE = { A: ["#7BD94F", "#2E7D14"], B: ["#FF6159", "#A3191A"], X: ["#5AA8FF", "#1655B8"], Y: ["#FFD24A", "#B88300"] };
const DEAD = 0.08;

const buzz = () => navigator.vibrate?.(6);

function Stick({ onMove, onClick, testid, className }) {
  const base = useRef(null);
  const knob = useRef(null);
  const active = useRef(null);
  const tap = useRef(0);

  const update = (e) => {
    const r = base.current.getBoundingClientRect();
    const rad = r.width / 2;
    let dx = e.clientX - (r.left + rad);
    let dy = e.clientY - (r.top + rad);
    const d = Math.hypot(dx, dy);
    if (d > rad) { dx = (dx / d) * rad; dy = (dy / d) * rad; }
    knob.current.style.transform = `translate(${dx * 0.62}px, ${dy * 0.62}px)`;
    const mag = Math.min(1, d / rad);
    const k = mag < DEAD ? 0 : (mag - DEAD) / (1 - DEAD) / (mag || 1); // radial deadzone, full range after it
    onMove(+((dx / rad) * k).toFixed(3), +((dy / rad) * k).toFixed(3));
  };
  const down = (e) => {
    active.current = e.pointerId;
    e.currentTarget.setPointerCapture(e.pointerId);
    knob.current.style.transition = "none";
    const now = Date.now();
    if (now - tap.current < 280) onClick(true); // double tap = L3/R3
    tap.current = now;
    update(e);
  };
  const move = (e) => active.current === e.pointerId && update(e);
  const up = (e) => {
    if (active.current !== e.pointerId) return;
    active.current = null;
    knob.current.style.transition = "transform 90ms ease-out";
    knob.current.style.transform = "translate(0,0)";
    onMove(0, 0);
    onClick(false);
  };

  return (
    <div ref={base} data-testid={testid} onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up}
      className={`pointer-events-auto absolute flex h-32 w-32 items-center justify-center rounded-full ${className}`}
      style={{ background: "radial-gradient(circle at 50% 40%, rgba(60,60,60,.55), rgba(10,10,10,.65))", boxShadow: "inset 0 2px 8px rgba(0,0,0,.8), 0 0 0 2px rgba(255,255,255,.08)", touchAction: "none" }}>
      <div ref={knob} className="pointer-events-none flex h-16 w-16 items-center justify-center rounded-full"
        style={{ background: "radial-gradient(circle at 50% 35%, #5a5a5a, #1d1d1d 70%)", boxShadow: "0 4px 10px rgba(0,0,0,.6), inset 0 -3px 6px rgba(0,0,0,.6)" }}>
        <div className="h-10 w-10 rounded-full" style={{ background: "radial-gradient(circle at 50% 60%, #2a2a2a, #3f3f3f)", boxShadow: "inset 0 2px 4px rgba(0,0,0,.7)" }} />
      </div>
    </div>
  );
}

function Btn({ id, onPress, className = "", style, children }) {
  const handle = (down) => (e) => {
    e.preventDefault();
    if (down) { e.currentTarget.setPointerCapture?.(e.pointerId); buzz(); }
    e.currentTarget.dataset.on = down ? "1" : "";
    onPress(id, down);
  };
  return (
    <button type="button" data-testid={`vpad-${id.toLowerCase()}`} onPointerDown={handle(true)} onPointerUp={handle(false)}
      onPointerCancel={handle(false)} onContextMenu={(e) => e.preventDefault()} style={{ touchAction: "none", ...style }}
      className={`pointer-events-auto flex select-none items-center justify-center font-bold transition-transform duration-75 data-[on=1]:scale-90 data-[on=1]:brightness-150 ${className}`}>
      {children}
    </button>
  );
}

function Face({ id, onPress, className }) {
  const [hi, lo] = FACE[id];
  return (
    <Btn id={id} onPress={onPress} className={`absolute h-14 w-14 rounded-full text-xl ${className}`}
      style={{ color: "#fff", textShadow: `0 0 6px ${hi}`, background: `radial-gradient(circle at 50% 30%, ${hi}, ${lo} 75%)`, opacity: 0.82, boxShadow: "0 3px 8px rgba(0,0,0,.55), inset 0 2px 2px rgba(255,255,255,.35)" }}>
      {id}
    </Btn>
  );
}

const SILVER = { background: "linear-gradient(180deg, rgba(210,210,215,.55), rgba(110,110,120,.55))", boxShadow: "0 2px 6px rgba(0,0,0,.5)", color: "#111" };
const DARK = { background: "linear-gradient(180deg, rgba(70,70,75,.7), rgba(25,25,28,.7))", boxShadow: "0 2px 6px rgba(0,0,0,.5), inset 0 1px 1px rgba(255,255,255,.15)", color: "#ddd" };

function DPad({ onPress }) {
  const arm = "absolute h-11 w-11 text-xs";
  return (
    <div className="absolute bottom-4 left-44 h-[132px] w-[132px]">
      <div className="absolute left-1/2 top-1/2 h-11 w-11 -translate-x-1/2 -translate-y-1/2" style={DARK} />
      <Btn id="UP" onPress={onPress} className={`${arm} left-1/2 top-0 -translate-x-1/2 rounded-t-md`} style={DARK}>▲</Btn>
      <Btn id="DOWN" onPress={onPress} className={`${arm} bottom-0 left-1/2 -translate-x-1/2 rounded-b-md`} style={DARK}>▼</Btn>
      <Btn id="LEFT" onPress={onPress} className={`${arm} left-0 top-1/2 -translate-y-1/2 rounded-l-md`} style={DARK}>◀</Btn>
      <Btn id="RIGHT" onPress={onPress} className={`${arm} right-0 top-1/2 -translate-y-1/2 rounded-r-md`} style={DARK}>▶</Btn>
    </div>
  );
}

// Xbox 360 layout: left stick high / D-pad low, face buttons high / right stick low
export default function VirtualGamepad({ send }) {
  const st = useRef({ b: 0, axes: [0, 0, 0, 0], lt: 0, rt: 0 });
  const emit = useCallback(() => send({ t: "gp", slot: 0, ...st.current, axes: [...st.current.axes] }), [send]);

  useEffect(() => {
    const t = setInterval(emit, 100); // heartbeat: repairs any lost packet on the fast channel
    return () => { clearInterval(t); st.current = { b: 0, axes: [0, 0, 0, 0], lt: 0, rt: 0 }; emit(); };
  }, [emit]);

  const press = useCallback((id, down) => {
    if (id === "LT" || id === "RT") st.current[id.toLowerCase()] = down ? 1 : 0;
    else st.current.b = down ? st.current.b | (1 << BIT[id]) : st.current.b & ~(1 << BIT[id]);
    emit();
  }, [emit]);
  const stick = (i) => (x, y) => { st.current.axes[i] = x; st.current.axes[i + 1] = y; emit(); };

  return (
    <div className="pointer-events-none absolute inset-0 z-20 select-none" data-testid="virtual-gamepad">
      <div className="absolute left-4 top-14 flex gap-2">
        <Btn id="LT" onPress={press} className="h-12 w-16 rounded-b-md rounded-t-2xl text-xs" style={DARK}>LT</Btn>
        <Btn id="LB" onPress={press} className="h-10 w-20 rounded-full text-xs" style={DARK}>LB</Btn>
      </div>
      <div className="absolute right-4 top-14 flex gap-2">
        <Btn id="RB" onPress={press} className="h-10 w-20 rounded-full text-xs" style={DARK}>RB</Btn>
        <Btn id="RT" onPress={press} className="h-12 w-16 rounded-b-md rounded-t-2xl text-xs" style={DARK}>RT</Btn>
      </div>

      <Stick testid="vpad-left-stick" className="bottom-28 left-8" onMove={stick(0)} onClick={(d) => press("LS", d)} />
      <DPad onPress={press} />

      <div className="absolute bottom-5 left-1/2 flex -translate-x-1/2 items-center gap-4">
        <Btn id="BACK" onPress={press} className="h-8 w-10 rounded-full text-[10px]" style={SILVER}>◀</Btn>
        <Btn id="GUIDE" onPress={press} className="h-12 w-12 rounded-full text-lg"
          style={{ ...SILVER, color: "#3BD13B", boxShadow: "0 0 0 3px rgba(59,209,59,.55), 0 0 14px rgba(59,209,59,.6)" }}>X</Btn>
        <Btn id="START" onPress={press} className="h-8 w-10 rounded-full text-[10px]" style={SILVER}>▶</Btn>
      </div>

      <div className="absolute bottom-28 right-6 h-[150px] w-[150px]">
        <Face id="Y" onPress={press} className="left-1/2 top-0 -translate-x-1/2" />
        <Face id="A" onPress={press} className="bottom-0 left-1/2 -translate-x-1/2" />
        <Face id="X" onPress={press} className="left-0 top-1/2 -translate-y-1/2" />
        <Face id="B" onPress={press} className="right-0 top-1/2 -translate-y-1/2" />
      </div>
      <Stick testid="vpad-right-stick" className="bottom-4 right-48" onMove={stick(2)} onClick={(d) => press("RS", d)} />
    </div>
  );
}
