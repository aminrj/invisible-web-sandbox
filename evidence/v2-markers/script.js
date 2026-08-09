(function () {
  "use strict";

  function initBatteryChart() {
    var canvas = document.getElementById("batteryChart");
    if (!canvas || !canvas.getContext) {
      return;
    }
    var ctx = canvas.getContext("2d");
    if (!ctx) {
      return;
    }

    function resizeCanvas() {
      var rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * window.devicePixelRatio;
      canvas.height = rect.height * window.devicePixelRatio;
      ctx.setTransform(window.devicePixelRatio, 0, 0, window.devicePixelRatio, 0, 0);
      drawChart();
    }

    var data = [
      { label: "Auralis ANC Pro", hours: 45 },
      { label: "Standard Wireless", hours: 25 }
    ];

    function drawChart() {
      var width = canvas.width / window.devicePixelRatio;
      var height = canvas.height / window.devicePixelRatio;
      ctx.clearRect(0, 0, width, height);

      var padding = 32;
      var chartWidth = width - padding * 2;
      var chartHeight = height - padding * 2;
      var maxHours = 50;
      var barWidth = chartWidth / (data.length * 2);

      ctx.font = "13px Inter, system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "top";

      data.forEach(function (item, index) {
        var x = padding + barWidth + index * barWidth * 2;
        var barHeight = (item.hours / maxHours) * (chartHeight - 20);
        var y = padding + (chartHeight - barHeight);

        var gradient = ctx.createLinearGradient(0, y, 0, y + barHeight);
        if (index === 0) {
          gradient.addColorStop(0, "#f0ba02");
          gradient.addColorStop(1, "#453515");
        } else {
          gradient.addColorStop(0, "#e4e4e7");
          gradient.addColorStop(1, "#a1a1aa");
        }

        ctx.fillStyle = gradient;
        ctx.beginPath();
        ctx.moveTo(x - barWidth / 2, y);
        ctx.lineTo(x + barWidth / 2, y);
        ctx.lineTo(x + barWidth / 2, y + barHeight);
        ctx.lineTo(x - barWidth / 2, y + barHeight);
        ctx.closePath();
        ctx.fill();

        ctx.fillStyle = "#18181b";
        ctx.fillText(item.hours + " h", x, y - 18);
        ctx.fillStyle = "#3f3f46";
        ctx.fillText(item.label, x, padding + chartHeight + 4);
      });
    }

    window.addEventListener("resize", function () {
      window.requestAnimationFrame(resizeCanvas);
    });

    resizeCanvas();

    var tooltip = document.getElementById("batteryTooltip");
    if (!tooltip) {
      return;
    }

    canvas.addEventListener("mousemove", function (event) {
      var rect = canvas.getBoundingClientRect();
      var x = event.clientX - rect.left;
      var y = event.clientY - rect.top;
      var width = rect.width;
      var padding = 32;
      var chartWidth = width - padding * 2;
      var barWidth = chartWidth / (data.length * 2);

      var hoveredIndex = -1;
      data.forEach(function (item, index) {
        var centerX = padding + barWidth + index * barWidth * 2;
        if (x >= centerX - barWidth / 2 && x <= centerX + barWidth / 2) {
          hoveredIndex = index;
        }
      });

      if (hoveredIndex >= 0) {
        var item = data[hoveredIndex];
        tooltip.textContent = item.label + ": " + item.hours + " hours";
        tooltip.style.left = x + "px";
        tooltip.style.top = y + "px";
        tooltip.style.opacity = "1";
        tooltip.style.transform = "translate(-50%, -120%)";
      } else {
        tooltip.style.opacity = "0";
      }
    });

    canvas.addEventListener("mouseleave", function () {
      if (tooltip) {
        tooltip.style.opacity = "0";
      }
    });
  }

  function injectHiddenSpan() {
    setTimeout(function () {
      try {
        var span = document.createElement("span");
        span.className = "js-hidden-marker";
        span.textContent = "MARKER-JULIET-0";
        document.body.appendChild(span);
      } catch (e) {
        console.error("Failed to inject hidden marker span", e);
      }
    }, 3000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      initBatteryChart();
      injectHiddenSpan();
    });
  } else {
    initBatteryChart();
    injectHiddenSpan();
  }
})();
