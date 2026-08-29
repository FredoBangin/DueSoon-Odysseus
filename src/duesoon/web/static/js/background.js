// Selectively adapted from Odysseus' constellation theme effect. The login
// surface needs the animation without booting the full legacy theme runtime.
export function startConstellations() {
  if (document.getElementById("constellations-canvas")) return;

  const canvas = document.createElement("canvas");
  canvas.id = "constellations-canvas";
  canvas.style.cssText = "position:fixed;inset:0;width:100%;height:100%;pointer-events:none;z-index:0";
  canvas.setAttribute("aria-hidden", "true");
  document.body.prepend(canvas);

  const context = canvas.getContext("2d");
  if (!context) return;

  const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
  const starCount = 50;
  const connectionDistance = 120;
  let width = 0;
  let height = 0;
  let stars = [];
  let time = 0;

  function createStars() {
    stars = Array.from({length: starCount}, () => ({
      x: Math.random() * width,
      y: Math.random() * height,
      vx: (Math.random() - 0.5) * 0.15,
      vy: (Math.random() - 0.5) * 0.15,
      radius: 0.8 + Math.random() * 0.8,
      phase: Math.random() * Math.PI * 2,
    }));
  }

  function resize() {
    width = window.innerWidth;
    height = window.innerHeight;
    canvas.width = width * pixelRatio;
    canvas.height = height * pixelRatio;
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    createStars();
  }

  function color() {
    const styles = getComputedStyle(document.documentElement);
    return styles.getPropertyValue("--bg-effect-color").trim()
      || styles.getPropertyValue("--fg").trim()
      || "#9cdef2";
  }

  function draw() {
    if (!document.body.classList.contains("bg-pattern-constellations")) {
      window.removeEventListener("resize", resize);
      canvas.remove();
      return;
    }

    requestAnimationFrame(draw);
    time += 0.01;
    context.clearRect(0, 0, width, height);
    const effectColor = color();

    for (const star of stars) {
      star.x += star.vx;
      star.y += star.vy;
      if (star.x < 0) star.x = width;
      if (star.x > width) star.x = 0;
      if (star.y < 0) star.y = height;
      if (star.y > height) star.y = 0;
    }

    context.strokeStyle = effectColor;
    context.lineWidth = 0.5;
    for (let first = 0; first < stars.length; first += 1) {
      for (let second = first + 1; second < stars.length; second += 1) {
        const xDistance = stars[first].x - stars[second].x;
        const yDistance = stars[first].y - stars[second].y;
        const distance = Math.hypot(xDistance, yDistance);
        if (distance >= connectionDistance) continue;
        context.globalAlpha = (1 - distance / connectionDistance) * 0.15;
        context.beginPath();
        context.moveTo(stars[first].x, stars[first].y);
        context.lineTo(stars[second].x, stars[second].y);
        context.stroke();
      }
    }

    context.fillStyle = effectColor;
    for (const star of stars) {
      const twinkle = 0.5 + 0.5 * Math.sin(time * 2 + star.phase);
      context.globalAlpha = 0.15 + twinkle * 0.25;
      context.beginPath();
      context.arc(star.x, star.y, star.radius, 0, Math.PI * 2);
      context.fill();
    }
    context.globalAlpha = 1;
  }

  resize();
  window.addEventListener("resize", resize);
  draw();
}
