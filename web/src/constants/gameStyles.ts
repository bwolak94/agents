export const GAME_CSS = `
  @import url('https://fonts.googleapis.com/css2?family=Press+Start+2P&display=swap');

  .pf { font-family: 'Press Start 2P', monospace; }

  @keyframes agentWalk {
    0%   { transform: translateY(0px) scale(1); }
    25%  { transform: translateY(-5px) scale(1.05); }
    50%  { transform: translateY(0px) scale(1); }
    75%  { transform: translateY(-3px) scale(1.02); }
  }
  @keyframes agentThink {
    0%,100% { filter: brightness(1); transform: scale(1); }
    50%     { filter: brightness(1.6); transform: scale(1.15); }
  }
  @keyframes agentDone {
    0%   { transform: scale(1) rotate(0deg); }
    20%  { transform: scale(1.4) rotate(-15deg); }
    40%  { transform: scale(1.4) rotate(15deg); }
    60%  { transform: scale(1.2) rotate(-8deg); }
    80%  { transform: scale(1.2) rotate(8deg); }
    100% { transform: scale(1) rotate(0deg); }
  }
  @keyframes agentSpawn {
    0%   { transform: scale(0) rotate(360deg); opacity: 0; }
    70%  { transform: scale(1.3) rotate(-10deg); opacity: 1; }
    100% { transform: scale(1) rotate(0deg); opacity: 1; }
  }
  @keyframes agentFade {
    0%   { transform: scale(1); opacity: 1; }
    100% { transform: scale(0) translateY(-20px); opacity: 0; }
  }
  @keyframes bubblePop {
    0%   { transform: scale(0.5) translateY(4px); opacity: 0; }
    60%  { transform: scale(1.05) translateY(0); opacity: 1; }
    100% { transform: scale(1) translateY(0); opacity: 1; }
  }
  @keyframes zoneGlow {
    0%,100% { box-shadow: inset 0 0 20px rgba(0,0,0,0.6); }
    50%     { box-shadow: inset 0 0 30px rgba(0,0,0,0.3); }
  }
  @keyframes eventSlide {
    from { transform: translateX(20px); opacity: 0; }
    to   { transform: translateX(0); opacity: 1; }
  }
  @keyframes counterPop {
    0%   { transform: scale(1); }
    50%  { transform: scale(1.4); }
    100% { transform: scale(1); }
  }
  @keyframes routingPulse {
    0%,100% { opacity: 0.6; }
    50%     { opacity: 1; }
  }
  @keyframes dotBounce {
    0%,80%,100% { transform: scale(0.6); opacity: 0.4; }
    40%         { transform: scale(1); opacity: 1; }
  }

  .walk  { animation: agentWalk  0.5s ease-in-out infinite; }
  .think { animation: agentThink 0.8s ease-in-out infinite; }
  .done  { animation: agentDone  0.6s ease-in-out; }
  .spawn { animation: agentSpawn 0.4s cubic-bezier(.36,.07,.19,.97) forwards; }
  .fade  { animation: agentFade  0.5s ease-in forwards; }
  .bubble-pop  { animation: bubblePop  0.3s cubic-bezier(.36,.07,.19,.97) forwards; }
  .event-slide { animation: eventSlide 0.25s ease-out; }
  .counter-pop { animation: counterPop 0.3s ease-out; }
  .routing-pulse { animation: routingPulse 1s ease-in-out infinite; }

  .zone-cell {
    position: relative;
    overflow: hidden;
    transition: border-color 0.3s ease;
  }
  .zone-cell::after {
    content: '';
    position: absolute;
    inset: 0;
    background: repeating-linear-gradient(
      0deg,
      transparent,
      transparent 3px,
      rgba(0,0,0,0.08) 3px,
      rgba(0,0,0,0.08) 4px
    );
    pointer-events: none;
  }
  .zone-active { animation: zoneGlow 2s ease-in-out infinite; }
  .crt-overlay {
    position: absolute;
    inset: 0;
    background: repeating-linear-gradient(
      0deg,
      transparent,
      transparent 2px,
      rgba(0,0,0,0.03) 2px,
      rgba(0,0,0,0.03) 4px
    );
    pointer-events: none;
    z-index: 10;
  }
`;
