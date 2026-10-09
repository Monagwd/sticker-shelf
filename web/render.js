/* 表情包小抽屉 · 把一段文字里的 [sticker:编号] 换成图片。
 * 拷到你自己的聊天前端里就能用：
 *
 *   <script src="http://127.0.0.1:8767/render.js"></script>
 *   StickerShelf.render(messageElement, replyText, "http://127.0.0.1:8767");
 *
 * 文字一律当纯文本放进去（不经过 innerHTML），不会被注入 HTML。
 */
(function (global) {
  "use strict";
  var MARKER = /\[sticker:(u-[a-f0-9]{10})\]/g;

  function render(container, text, base) {
    base = (base || "").replace(/\/$/, "");
    container.textContent = "";
    var source = String(text || "");
    var last = 0;
    var match;
    MARKER.lastIndex = 0;
    while ((match = MARKER.exec(source)) !== null) {
      appendText(container, source.slice(last, match.index));
      var img = document.createElement("img");
      img.className = "sticker";
      img.alt = "表情包";
      img.loading = "lazy";
      img.src = base + "/stickers/img/" + match[1];
      img.onerror = function () { this.replaceWith(document.createTextNode("【一张已删除的表情包】")); };
      container.appendChild(img);
      last = MARKER.lastIndex;
    }
    appendText(container, source.slice(last));
  }

  function appendText(container, text) {
    if (!text) return;
    var lines = text.split("\n");
    lines.forEach(function (line, index) {
      if (index) container.appendChild(document.createElement("br"));
      if (line) container.appendChild(document.createTextNode(line));
    });
  }

  global.StickerShelf = { render: render, MARKER: MARKER };
})(window);
