window.addEventListener('load', () => {
  const msgEl = document.getElementById('takeover-message');
  if (!msgEl) return console.error('No #takeover-message found!');

  const txt = 'Quote smarter, sell faster—effortless proposals powered by AI.';
  let i = 0;

  msgEl.style.opacity = 1;        // fade it in
  msgEl.style.width   = 'auto';   // ensure it can grow

  function type() {
    if (i < txt.length) {
      msgEl.textContent += txt[i++];
      setTimeout(type, 80);
    }
  }
  type();
});
// 2️⃣  Floating nodes network
const canvas = document.getElementById('node-canvas');
if (canvas) {
  const ctx = canvas.getContext('2d');
  const nodes = Array.from({ length: 60 }, () => ({
    x: Math.random() * canvas.width,
    y: Math.random() * canvas.height,
    vx: (Math.random() - .5) * .4,
    vy: (Math.random() - .5) * .4
  }));

  function resize() {
    const container = document.querySelector('.login-right');
    canvas.width = container.clientWidth;
    canvas.height = container.clientHeight;
  }

  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    nodes.forEach((n, i) => {
      n.x += n.vx; n.y += n.vy;
      if (n.x < 0 || n.x > canvas.width) n.vx *= -1;
      if (n.y < 0 || n.y > canvas.height) n.vy *= -1;

      ctx.beginPath();
      ctx.arc(n.x, n.y, 2.5, 0, Math.PI * 1);
      ctx.fillStyle = 'rgba(225, 84, 19, 0.87)';
      ctx.fill();

      for (let j = i + 1; j < nodes.length; j++) {
        const m = nodes[j];
        const d = Math.hypot(n.x - m.x, n.y - m.y);
        if (d < 80) {
          ctx.strokeStyle = `rgba(252,106,61,${1 - d / 80})`;
          ctx.beginPath();
          ctx.moveTo(n.x, n.y);
          ctx.lineTo(m.x, m.y);
          ctx.stroke();
        }
      }
    });
    requestAnimationFrame(draw);
  }

  resize();
  draw();
  window.addEventListener('resize', resize);
}
