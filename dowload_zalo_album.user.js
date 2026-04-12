// ==UserScript==
// @name         Zalo Chat XPath Image Downloader
// @namespace    https://chat.zalo.me/
// @version      1.0.2
// @description  Nhap XPath, dem anh va tai anh theo thu tu tren Zalo Chat
// @author       GPT
// @match        https://chat.zalo.me/*
// @updateURL    https://raw.githubusercontent.com/NguyenKz/image_to_pdf/main/dowload_zalo_album.meta.js
// @downloadURL  https://raw.githubusercontent.com/NguyenKz/image_to_pdf/main/dowload_zalo_album.user.js
// @run-at       document-idle
// @grant        none
// ==/UserScript==

(function () {
  "use strict";



  const PANEL_ID = "xpath-image-downloader-panel";
  const TOAST_CONTAINER_ID = `${PANEL_ID}-toast-container`;
  const QUEUE_BUTTON_ID = `${PANEL_ID}-queue-download`;
  const PROGRESS_PANEL_ID = `${PANEL_ID}-progress`;
  const DEFAULT_ALBUM_XPATH =
    '//*[@id="album-container"]/div[contains(concat(" ", normalize-space(@class), " "), " album ")]';
  const THUMB_ID_SUFFIX = "-MESSAGE_LIST_GROUP_PHOTO";
  const VIEWER_ID_SUFFIX = "-IMAGE_VIEWER";
  const PAGE_SETTLE_MS = 1500;
  const MAX_WAIT_MS = 3000;
  const MAX_IMAGE_DOWNLOAD_RETRIES = 3;
  if (document.getElementById(PANEL_ID)) {
    return;
  }

  function padIndex(index) {
    return String(index).padStart(8, "0");
  }

  function padAlbumIndex(index) {
    return String(index).padStart(2, "0");
  }

  function padOverlayImageIndex(index) {
    return String(index).padStart(5, "0");
  }

  function buildImageFileName(timestamp, albumIndex, imageIndex, extension) {
    return `${timestamp}_${padAlbumIndex(albumIndex)}-${padIndex(imageIndex)}.${extension}`;
  }

  function buildPdfFileName(timestamp, albumIndex) {
    return `${timestamp}_album-${padAlbumIndex(albumIndex)}.pdf`;
  }

  function normalizeUrl(url) {
    if (!url) return null;
    return url.replace(/^blob:/, "");
  }

  function getExtensionFromUrl(url) {
    try {
      const cleanUrl = url.split("?")[0].split("#")[0];
      const match = cleanUrl.match(/\.([a-zA-Z0-9]+)$/);
      return match ? match[1].toLowerCase() : "jpg";
    } catch {
      return "jpg";
    }
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function waitForBody() {
    return new Promise((resolve) => {
      if (document.body) {
        resolve();
        return;
      }

      const observer = new MutationObserver(() => {
        if (document.body) {
          observer.disconnect();
          resolve();
        }
      });

      observer.observe(document.documentElement, { childList: true, subtree: true });
    });
  }

  function waitForDocumentComplete() {
    return new Promise((resolve) => {
      const timeoutId = setTimeout(() => {
        document.removeEventListener("readystatechange", onReadyStateChange);
        window.removeEventListener("load", onReadyStateChange);
        resolve();
      }, MAX_WAIT_MS);

      if (document.readyState === "complete") {
        clearTimeout(timeoutId);
        resolve();
        return;
      }

      const onReadyStateChange = () => {
        if (document.readyState === "complete") {
          clearTimeout(timeoutId);
          document.removeEventListener("readystatechange", onReadyStateChange);
          window.removeEventListener("load", onReadyStateChange);
          resolve();
        }
      };

      document.addEventListener("readystatechange", onReadyStateChange);
      window.addEventListener("load", onReadyStateChange, { once: true });
    });
  }

  function waitForPageToSettle() {
    return new Promise((resolve) => {
      let settleTimer = null;
      let maxTimer = null;

      const finish = () => {
        if (settleTimer) {
          clearTimeout(settleTimer);
        }
        if (maxTimer) {
          clearTimeout(maxTimer);
        }
        observer.disconnect();
        resolve();
      };

      const scheduleSettleCheck = () => {
        if (settleTimer) {
          clearTimeout(settleTimer);
        }
        settleTimer = setTimeout(finish, PAGE_SETTLE_MS);
      };

      const observer = new MutationObserver(() => {
        scheduleSettleCheck();
      });

      observer.observe(document.body, {
        childList: true,
        subtree: true,
        attributes: true,
      });

      maxTimer = setTimeout(finish, MAX_WAIT_MS);
      scheduleSettleCheck();
    });
  }

  function evaluateXPath(xpath, contextNode = document) {
    const result = document.evaluate(
      xpath,
      contextNode,
      null,
      XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,
      null
    );

    const nodes = [];
    for (let i = 0; i < result.snapshotLength; i += 1) {
      nodes.push(result.snapshotItem(i));
    }

    return nodes;
  }

  function getImageUrlFromNode(node) {
    if (!node) return null;

    if (node.tagName && node.tagName.toLowerCase() === "img") {
      return (
        node.currentSrc ||
        node.src ||
        node.getAttribute("data-src") ||
        node.getAttribute("data-original") ||
        null
      );
    }

    const img = node.querySelector("img");
    if (!img) return null;

    return (
      img.currentSrc ||
      img.src ||
      img.getAttribute("data-src") ||
      img.getAttribute("data-original") ||
      null
    );
  }

  function getImageNodesFromAlbum(albumNode) {
    const zimgNodes = Array.from(albumNode.getElementsByClassName("zimg-el"));
    if (zimgNodes.length > 0) {
      return zimgNodes;
    }

    return Array.from(albumNode.getElementsByTagName("img"));
  }

  function getImageIdFromNode(node) {
    if (!node) return null;

    if (node.tagName && node.tagName.toLowerCase() === "img") {
      return node.id || null;
    }

    const img = node.querySelector("img");
    return img?.id || null;
  }

  function getImageBaseId(imageNode) {
    const imageId = getImageIdFromNode(imageNode);
    if (!imageId) return null;

    if (imageId.endsWith(THUMB_ID_SUFFIX)) {
      return imageId.slice(0, -THUMB_ID_SUFFIX.length);
    }

    if (imageId.endsWith(VIEWER_ID_SUFFIX)) {
      return imageId.slice(0, -VIEWER_ID_SUFFIX.length);
    }

    return imageId;
  }

  async function waitForCondition(checkFn, timeoutMs = 8000, intervalMs = 120) {
    const startedAt = Date.now();

    while (Date.now() - startedAt < timeoutMs) {
      const result = checkFn();
      if (result) {
        return result;
      }
      await sleep(intervalMs);
    }

    throw new Error("Het thoi gian cho doi doi tuong full image");
  }

  async function waitForViewerImageByBaseId(baseId, timeoutMs = 8000) {
    const viewerId = `${baseId}${VIEWER_ID_SUFFIX}`;

    return waitForCondition(() => {
      const viewerNode = document.getElementById(viewerId);
      const viewerSrc = viewerNode?.currentSrc || viewerNode?.src || null;

      if (!viewerNode || !viewerSrc) {
        return null;
      }

      return {
        node: viewerNode,
        rawUrl: viewerSrc,
        url: normalizeUrl(viewerSrc) || viewerSrc,
      };
    }, timeoutMs);
  }

  function closeImageViewer() {
    document.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Escape",
        code: "Escape",
        keyCode: 27,
        which: 27,
        bubbles: true,
      })
    );
  }

  async function openFullImageFromThumbnail(image) {
    if (!image.thumbNode) {
      throw new Error("Khong tim thay thumbnail de mo full image");
    }

    if (!image.baseId) {
      throw new Error("Khong tim thay img-id cua thumbnail");
    }

    image.thumbNode.click();
    const viewerImage = await waitForViewerImageByBaseId(image.baseId);

    return {
      ...image,
      rawUrl: viewerImage.rawUrl,
      url: viewerImage.url,
    };
  }

  async function fetchBlobFromCandidateUrls(urls) {
    const uniqueUrls = [...new Set(urls.filter(Boolean))];
    let lastError = null;

    for (const url of uniqueUrls) {
      try {
        const response = await fetch(url);
        if (!response.ok) {
          throw new Error(`Cannot download: ${url}`);
        }
        return response.blob();
      } catch (error) {
        lastError = error;
      }
    }

    throw lastError || new Error("Khong tai duoc anh");
  }

  async function downloadImage(image) {
    const blob = await fetchBlobFromCandidateUrls([image.url, image.rawUrl]);
    const blobUrl = URL.createObjectURL(blob);

    const a = document.createElement("a");
    a.href = blobUrl;
    a.download = image.name;
    document.body.appendChild(a);
    a.click();
    a.remove();

    setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
  }

  async function fetchImageBlob(image) {
    return fetchBlobFromCandidateUrls([image.url, image.rawUrl]);
  }

  function loadImageFromBlob(blob) {
    return new Promise((resolve, reject) => {
      const objectUrl = URL.createObjectURL(blob);
      const img = new Image();
      img.onload = () => {
        URL.revokeObjectURL(objectUrl);
        resolve(img);
      };
      img.onerror = () => {
        URL.revokeObjectURL(objectUrl);
        reject(new Error("Khong mo duoc anh de tao PDF"));
      };
      img.src = objectUrl;
    });
  }

  function imageToJpegDataUrl(imageElement, quality = 0.92) {
    const width = imageElement.naturalWidth || imageElement.width;
    const height = imageElement.naturalHeight || imageElement.height;

    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;

    const context = canvas.getContext("2d");
    if (!context) {
      throw new Error("Khong tao duoc canvas de tao PDF");
    }

    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, width, height);
    context.drawImage(imageElement, 0, 0, width, height);

    return {
      dataUrl: canvas.toDataURL("image/jpeg", quality),
      width,
      height,
    };
  }

  function getJsPdfCtor() {
    if (typeof jspdf !== "undefined" && jspdf?.jsPDF) {
      return jspdf.jsPDF;
    }
    if (typeof globalThis !== "undefined" && globalThis.jspdf?.jsPDF) {
      return globalThis.jspdf.jsPDF;
    }
    if (typeof window !== "undefined" && window.jspdf?.jsPDF) {
      return window.jspdf.jsPDF;
    }
    if (typeof window !== "undefined" && typeof window.jsPDF !== "undefined") {
      return window.jsPDF;
    }
    return null;
  }

  async function ensureJsPdfLoaded() {
    const existingCtor = getJsPdfCtor();
    if (existingCtor) {
      return existingCtor;
    }
    throw new Error("Khong tim thay jsPDF tu @require trong Tampermonkey");
  }

  async function downloadPdfFromImages(images, timestamp, albumIndex, onProgress = null) {
    const JsPdf = await ensureJsPdfLoaded();

    let pdf = null;

    for (let i = 0; i < images.length; i += 1) {
      const image = images[i];
      if (typeof onProgress === "function") {
        onProgress(i + 1, images.length, image);
      }
      const blob = await fetchImageBlob(image);
      const loadedImage = await loadImageFromBlob(blob);
      const jpegImage = imageToJpegDataUrl(loadedImage);
      const width = jpegImage.width;
      const height = jpegImage.height;
      const orientation = width > height ? "landscape" : "portrait";

      if (!pdf) {
        pdf = new JsPdf({
          orientation,
          unit: "px",
          format: [width, height],
          compress: true,
        });
      } else {
        pdf.addPage([width, height], orientation);
      }

      pdf.addImage(jpegImage.dataUrl, "JPEG", 0, 0, width, height);
    }

    if (!pdf) {
      throw new Error("Khong co anh de tao PDF");
    }

    pdf.save(buildPdfFileName(timestamp, albumIndex));
  }

  function injectStyles() {
    const styleId = `${PANEL_ID}-styles`;
    if (document.getElementById(styleId)) {
      return;
    }

    const style = document.createElement("style");
    style.id = styleId;
    style.textContent = `
      #${PANEL_ID} {
        position: fixed;
        top: 20px;
        right: 20px;
        z-index: 999999;
        min-width: 132px;
        padding: 12px 18px;
        border: none;
        border-radius: 999px;
        background: linear-gradient(135deg, #2563eb, #1d4ed8);
        box-shadow: 0 14px 30px rgba(37, 99, 235, 0.28);
        backdrop-filter: blur(10px);
        font-family: Inter, Arial, sans-serif;
        font-size: 14px;
        font-weight: 700;
        color: #ffffff;
        cursor: pointer;
        transition:
          transform 0.15s ease,
          box-shadow 0.15s ease,
          opacity 0.15s ease;
      }

      #${PANEL_ID}:hover:not(:disabled) {
        transform: translateY(-1px);
        box-shadow: 0 18px 34px rgba(37, 99, 235, 0.32);
      }

      #${PANEL_ID}:disabled {
        opacity: 0.7;
        cursor: default;
      }

      #${QUEUE_BUTTON_ID} {
        position: fixed;
        top: 78px;
        right: 20px;
        z-index: 999999;
        min-width: 164px;
        padding: 12px 18px;
        border: none;
        border-radius: 999px;
        background: linear-gradient(135deg, #16a34a, #15803d);
        box-shadow: 0 14px 30px rgba(22, 163, 74, 0.24);
        backdrop-filter: blur(10px);
        font-family: Inter, Arial, sans-serif;
        font-size: 14px;
        font-weight: 700;
        color: #ffffff;
        cursor: pointer;
        transition:
          transform 0.15s ease,
          box-shadow 0.15s ease,
          opacity 0.15s ease;
      }

      #${QUEUE_BUTTON_ID}:hover:not(:disabled) {
        transform: translateY(-1px);
        box-shadow: 0 18px 34px rgba(22, 163, 74, 0.3);
      }

      #${QUEUE_BUTTON_ID}:disabled {
        opacity: 0.7;
        cursor: default;
      }

      #${PROGRESS_PANEL_ID} {
        position: fixed;
        top: 136px;
        right: 20px;
        z-index: 999999;
        width: 320px;
        padding: 14px 16px;
        border-radius: 18px;
        background: rgba(15, 23, 42, 0.92);
        box-shadow: 0 16px 36px rgba(15, 23, 42, 0.28);
        backdrop-filter: blur(12px);
        color: #ffffff;
        font-family: Inter, Arial, sans-serif;
      }

      #${PROGRESS_PANEL_ID}[hidden] {
        display: none;
      }

      .tm-zalo-progress-title {
        font-size: 13px;
        font-weight: 800;
        line-height: 1.3;
      }

      .tm-zalo-progress-detail {
        margin-top: 6px;
        font-size: 12px;
        font-weight: 600;
        line-height: 1.4;
        color: rgba(255, 255, 255, 0.82);
      }

      .tm-zalo-progress-meta {
        margin-top: 10px;
        display: flex;
        justify-content: space-between;
        gap: 12px;
        font-size: 11px;
        font-weight: 700;
        color: rgba(255, 255, 255, 0.74);
      }

      .tm-zalo-progress-bar {
        margin-top: 8px;
        height: 10px;
        border-radius: 999px;
        background: rgba(148, 163, 184, 0.26);
        overflow: hidden;
      }

      .tm-zalo-progress-fill {
        height: 100%;
        width: 0%;
        border-radius: inherit;
        background: linear-gradient(135deg, #22c55e, #16a34a);
        transition: width 0.18s ease;
      }

      .tm-zalo-album-actions {
        position: absolute;
        top: 10px;
        right: 10px;
        z-index: 999998;
        display: flex;
        flex-wrap: wrap;
        justify-content: flex-end;
        gap: 8px;
        max-width: calc(100% - 20px);
      }

      .tm-zalo-album-select-btn,
      .tm-zalo-album-download-btn,
      .tm-zalo-album-pdf-btn {
        min-width: 112px;
        padding: 8px 12px;
        border: none;
        border-radius: 999px;
        background: linear-gradient(135deg, rgba(34, 197, 94, 0.96), rgba(22, 163, 74, 0.96));
        color: #ffffff;
        font-size: 12px;
        font-weight: 700;
        cursor: pointer;
        box-shadow: 0 10px 18px rgba(22, 163, 74, 0.24);
        transition:
          transform 0.15s ease,
          box-shadow 0.15s ease,
          opacity 0.15s ease;
      }

      .tm-zalo-album-select-btn {
        min-width: 88px;
        background: linear-gradient(135deg, rgba(59, 130, 246, 0.96), rgba(29, 78, 216, 0.96));
        box-shadow: 0 10px 18px rgba(29, 78, 216, 0.24);
      }

      .tm-zalo-album-select-btn.is-selected {
        background: linear-gradient(135deg, rgba(245, 158, 11, 0.96), rgba(217, 119, 6, 0.96));
        box-shadow: 0 10px 18px rgba(217, 119, 6, 0.26);
      }

      .tm-zalo-album-pdf-btn {
        min-width: 82px;
        background: linear-gradient(135deg, rgba(168, 85, 247, 0.96), rgba(124, 58, 237, 0.96));
        box-shadow: 0 10px 18px rgba(124, 58, 237, 0.24);
      }

      .tm-zalo-album-select-btn:hover:not(:disabled),
      .tm-zalo-album-download-btn:hover:not(:disabled),
      .tm-zalo-album-pdf-btn:hover:not(:disabled) {
        transform: translateY(-1px);
      }

      .tm-zalo-album-select-btn:hover:not(:disabled) {
        box-shadow: 0 14px 22px rgba(29, 78, 216, 0.28);
      }

      .tm-zalo-album-download-btn:hover:not(:disabled) {
        box-shadow: 0 14px 22px rgba(22, 163, 74, 0.28);
      }

      .tm-zalo-album-pdf-btn:hover:not(:disabled) {
        box-shadow: 0 14px 22px rgba(124, 58, 237, 0.28);
      }

      .tm-zalo-album-select-btn:disabled,
      .tm-zalo-album-download-btn:disabled,
      .tm-zalo-album-pdf-btn:disabled {
        opacity: 0.7;
        cursor: default;
      }

      .tm-zalo-album-selected {
        outline: 3px solid rgba(245, 158, 11, 0.9);
        outline-offset: -3px;
        border-radius: 16px;
      }

      .tm-zalo-album-select-order-badge {
        position: absolute;
        top: 10px;
        left: 10px;
        z-index: 999998;
        min-width: 36px;
        padding: 6px 10px;
        border-radius: 999px;
        background: rgba(245, 158, 11, 0.96);
        color: #ffffff;
        font-size: 12px;
        font-weight: 800;
        line-height: 1;
        text-align: center;
        box-shadow: 0 10px 20px rgba(217, 119, 6, 0.24);
        pointer-events: none;
      }

      .tm-zalo-image-index-badge {
        position: absolute;
        left: 8px;
        bottom: 8px;
        z-index: 999997;
        padding: 4px 8px;
        border: 1px solid rgba(255, 255, 255, 0.18);
        border-radius: 999px;
        background: rgba(15, 23, 42, 0.72);
        backdrop-filter: blur(6px);
        color: #ffffff;
        font-size: 11px;
        font-weight: 700;
        line-height: 1;
        letter-spacing: 0.02em;
        box-shadow: 0 8px 20px rgba(15, 23, 42, 0.24);
        pointer-events: none;
      }

      #${TOAST_CONTAINER_ID} {
        position: fixed;
        right: 20px;
        bottom: 20px;
        z-index: 1000000;
        display: flex;
        flex-direction: column;
        gap: 10px;
        pointer-events: none;
      }

      .tm-zalo-toast {
        min-width: 240px;
        max-width: 360px;
        padding: 12px 14px;
        border-radius: 14px;
        color: #ffffff;
        font-family: Inter, Arial, sans-serif;
        font-size: 13px;
        font-weight: 600;
        line-height: 1.4;
        box-shadow: 0 14px 28px rgba(15, 23, 42, 0.2);
        backdrop-filter: blur(8px);
        opacity: 0;
        transform: translateY(8px);
        transition:
          opacity 0.18s ease,
          transform 0.18s ease;
      }

      .tm-zalo-toast.is-visible {
        opacity: 1;
        transform: translateY(0);
      }

      .tm-zalo-toast--info {
        background: rgba(37, 99, 235, 0.94);
      }

      .tm-zalo-toast--success {
        background: rgba(22, 163, 74, 0.94);
      }

      .tm-zalo-toast--error {
        background: rgba(220, 38, 38, 0.94);
      }
    `;

    document.head.appendChild(style);
  }

  function getAlbumNodes(xpath) {
    try {
      return typeof window.$x === "function" ? window.$x(xpath) : evaluateXPath(xpath);
    } catch (error) {
      throw new Error(`XPath khong hop le: ${error.message}`);
    }
  }

  function collectImagesFromAlbum(albumNode, timestamp = null, albumIndex = 1) {
    const imageNodes = getImageNodesFromAlbum(albumNode);

    return imageNodes
      .map((imageNode, index) => {
        const rawUrl = getImageUrlFromNode(imageNode);
        if (!rawUrl) return null;

        const imageIndex = index + 1;
        const normalizedUrl = normalizeUrl(rawUrl);
        const extension = getExtensionFromUrl(normalizedUrl || rawUrl);

        return {
          index: imageIndex,
          albumIndex,
          thumbNode: imageNode,
          baseId: getImageBaseId(imageNode),
          rawUrl,
          url: normalizedUrl || rawUrl,
          name: timestamp
            ? buildImageFileName(timestamp, albumIndex, imageIndex, extension)
            : null,
        };
      })
      .filter(Boolean);
  }

  function collectAlbums(xpath) {
    const albumNodes = getAlbumNodes(xpath);

    return albumNodes.map((albumNode, index) => ({
      index: index + 1,
      node: albumNode,
      images: collectImagesFromAlbum(albumNode, null, index + 1),
    }));
  }

  function getFreshAlbum(xpath, albumIndex) {
    const albums = collectAlbums(xpath);
    const album = albums.find((item) => item.index === albumIndex) || null;
    return { albums, album };
  }

  function createPanel() {
    if (document.getElementById(PANEL_ID)) {
      return;
    }

    injectStyles();

    const refreshButton = document.createElement("button");
    refreshButton.id = PANEL_ID;
    refreshButton.textContent = "Lam moi";
    refreshButton.title = "Lam moi de quet lai cac album dang duoc load";

    const queueButton = document.createElement("button");
    queueButton.id = QUEUE_BUTTON_ID;
    queueButton.textContent = "Tai da chon";
    queueButton.title = "Chon album roi bam de tai theo thu tu da chon";

    const progressPanel = document.createElement("div");
    progressPanel.id = PROGRESS_PANEL_ID;
    progressPanel.hidden = true;
    progressPanel.innerHTML = `
      <div class="tm-zalo-progress-title">Dang cho thao tac</div>
      <div class="tm-zalo-progress-detail">Chua co tien trinh nao.</div>
      <div class="tm-zalo-progress-meta">
        <span class="tm-zalo-progress-count">0/0</span>
        <span class="tm-zalo-progress-percent">0%</span>
      </div>
      <div class="tm-zalo-progress-bar">
        <div class="tm-zalo-progress-fill"></div>
      </div>
    `;

    const toastContainer = document.createElement("div");
    toastContainer.id = TOAST_CONTAINER_ID;

    let labelResetTimer = null;
    let progressHideTimer = null;
    let isQueueDownloading = false;
    let selectedAlbumIndexes = [];
    let latestAlbums = [];
    const albumControls = new Map();
    const progressTitleNode = progressPanel.querySelector(".tm-zalo-progress-title");
    const progressDetailNode = progressPanel.querySelector(".tm-zalo-progress-detail");
    const progressCountNode = progressPanel.querySelector(".tm-zalo-progress-count");
    const progressPercentNode = progressPanel.querySelector(".tm-zalo-progress-percent");
    const progressFillNode = progressPanel.querySelector(".tm-zalo-progress-fill");

    function writeLog(message) {
      console.log(`[Zalo Album Downloader] ${message}`);
    }

    function showToast(message, type = "info", durationMs = 2600) {
      const toast = document.createElement("div");
      toast.className = `tm-zalo-toast tm-zalo-toast--${type}`;
      toast.textContent = message;
      toastContainer.appendChild(toast);

      requestAnimationFrame(() => {
        toast.classList.add("is-visible");
      });

      setTimeout(() => {
        toast.classList.remove("is-visible");
        setTimeout(() => toast.remove(), 220);
      }, durationMs);
    }

    function setRefreshLabel(label, title) {
      refreshButton.textContent = label;
      refreshButton.title = title || refreshButton.title;
    }

    function setProgress(title, detail, current, total, options = {}) {
      const safeTotal = Math.max(total || 0, 1);
      const clampedCurrent = Math.min(Math.max(current || 0, 0), safeTotal);
      const percent = Math.round((clampedCurrent / safeTotal) * 100);
      const countLabel =
        typeof options.countLabel === "string"
          ? options.countLabel
          : `${Math.floor(clampedCurrent)}/${safeTotal}`;

      if (progressHideTimer) {
        clearTimeout(progressHideTimer);
        progressHideTimer = null;
      }

      progressTitleNode.textContent = title;
      progressDetailNode.textContent = detail;
      progressCountNode.textContent = countLabel;
      progressPercentNode.textContent = `${percent}%`;
      progressFillNode.style.width = `${percent}%`;
      progressPanel.hidden = false;
    }

    function hideProgress(delayMs = 1600) {
      if (progressHideTimer) {
        clearTimeout(progressHideTimer);
      }

      progressHideTimer = setTimeout(() => {
        progressPanel.hidden = true;
      }, delayMs);
    }

    function syncRefreshButtonState() {
      refreshButton.disabled = isQueueDownloading;
      if (isQueueDownloading) {
        refreshButton.title = "Dang tai hang doi album, tam khoa Lam moi";
      } else if (refreshButton.textContent === "Lam moi") {
        refreshButton.title = "Lam moi de quet lai cac album dang duoc load";
      }
    }

    function updateQueueButton() {
      const selectedCount = selectedAlbumIndexes.length;
      queueButton.disabled = isQueueDownloading || selectedCount === 0;

      if (isQueueDownloading) {
        queueButton.title = "Dang tai hang doi album";
        return;
      }

      if (!selectedCount) {
        queueButton.textContent = "Tai da chon";
        queueButton.title = "Chon album roi bam de tai theo thu tu da chon";
        return;
      }

      queueButton.textContent = `Tai da chon (${selectedCount})`;
      queueButton.title = `Tai ${selectedCount} album theo thu tu da chon`;
    }

    function trimSelectedAlbums(albums) {
      const albumIndexSet = new Set(albums.map((album) => album.index));
      selectedAlbumIndexes = selectedAlbumIndexes.filter((albumIndex) => albumIndexSet.has(albumIndex));
    }

    function updateAlbumControls() {
      latestAlbums.forEach((album) => {
        const controls = albumControls.get(album.index);
        if (!controls) {
          return;
        }

        const selectionOrder = selectedAlbumIndexes.indexOf(album.index) + 1;
        const isSelected = selectionOrder > 0;

        controls.selectButton.textContent = isSelected ? `Chon #${selectionOrder}` : "Chon";
        controls.selectButton.title = isSelected
          ? `Bo chon album ${album.index}`
          : `Chon album ${album.index} vao hang doi tai`;
        controls.selectButton.disabled = isQueueDownloading;
        controls.selectButton.classList.toggle("is-selected", isSelected);

        controls.imageButton.disabled = isQueueDownloading;
        controls.albumNode.classList.toggle("tm-zalo-album-selected", isSelected);

        controls.orderBadge.hidden = !isSelected;
        controls.orderBadge.textContent = `#${selectionOrder}`;
      });

      syncRefreshButtonState();
      updateQueueButton();
    }

    function toggleAlbumSelection(albumIndex) {
      if (isQueueDownloading) {
        return;
      }

      const selectedIndex = selectedAlbumIndexes.indexOf(albumIndex);
      if (selectedIndex >= 0) {
        selectedAlbumIndexes.splice(selectedIndex, 1);
        writeLog(`Bo chon album ${albumIndex}.`);
      } else {
        selectedAlbumIndexes.push(albumIndex);
        writeLog(`Da chon album ${albumIndex} o vi tri ${selectedAlbumIndexes.length}.`);
      }

      updateAlbumControls();
    }

    function showRefreshSummary(albumCount, imageCount) {
      if (labelResetTimer) {
        clearTimeout(labelResetTimer);
      }

      setRefreshLabel(`${albumCount} album • ${imageCount} anh`, "Da quet xong");
      showToast(`Da quet xong ${albumCount} album, ${imageCount} anh.`, "success", 2200);

      labelResetTimer = setTimeout(() => {
        setRefreshLabel("Lam moi", "Lam moi de quet lai cac album dang duoc load");
      }, 2200);
    }

    async function resolveFreshAlbum(albumIndex) {
      const xpath = DEFAULT_ALBUM_XPATH;
      if (!xpath) {
        throw new Error("Chua nhap XPath.");
      }

      await sleep(400);

      const result = getFreshAlbum(xpath, albumIndex);
      if (!result.album) {
        throw new Error(`Khong tim thay lai album ${albumIndex}. Bam Lam moi roi thu lai.`);
      }

      return result.album;
    }

    async function downloadImageWithRetry(image, albumIndex) {
      let lastError = null;

      for (let attempt = 1; attempt <= MAX_IMAGE_DOWNLOAD_RETRIES; attempt += 1) {
        try {
          const fullImage = await openFullImageFromThumbnail(image);
          await downloadImage(fullImage);
          closeImageViewer();
          await sleep(150);
          await sleep(300);

          if (attempt > 1) {
            writeLog(
              `Tai lai thanh cong album ${albumIndex} - ${image.name} o lan ${attempt}/${MAX_IMAGE_DOWNLOAD_RETRIES}.`
            );
          }

          return;
        } catch (error) {
          lastError = error;
          closeImageViewer();
          await sleep(150);

          if (attempt < MAX_IMAGE_DOWNLOAD_RETRIES) {
            writeLog(
              `Anh ${image.name} cua album ${albumIndex} loi lan ${attempt}/${MAX_IMAGE_DOWNLOAD_RETRIES}: ${error.message}. Dang thu lai...`
            );
            showToast(
              `Anh ${image.index} cua album ${albumIndex} loi, thu lai lan ${attempt + 1}/${MAX_IMAGE_DOWNLOAD_RETRIES}.`,
              "info",
              1800
            );
            await sleep(350);
          }
        }
      }

      throw lastError || new Error("Khong tai duoc anh sau nhieu lan thu");
    }

    async function downloadAlbum(album, button, progressContext = null) {
      let freshAlbum = null;
      const failedImages = [];

      try {
        freshAlbum = await resolveFreshAlbum(album.index);
      } catch (error) {
        writeLog(`Khong the cap nhat lai album ${album.index}: ${error.message}`);
        setProgress("Khong the tai album", `Album ${album.index}: ${error.message}`, 0, 1);
        hideProgress(2600);
        return;
      }

      const timestamp = Date.now();
      const images = collectImagesFromAlbum(freshAlbum.node, timestamp, freshAlbum.index);

      if (!images.length) {
        writeLog(`Album ${freshAlbum.index} hien khong co anh. Bam Lam moi roi thu lai.`);
        showToast(`Album ${freshAlbum.index} hien khong co anh.`, "error");
        setProgress("Album khong co anh", `Album ${freshAlbum.index} hien khong co anh.`, 0, 1);
        hideProgress(2200);
        return;
      }

      if (button) {
        button.disabled = true;
        button.textContent = `Anh 0/${images.length}`;
      }

      writeLog(`Bat dau tai album ${freshAlbum.index} voi ${images.length} anh.`);
      showToast(`Dang tai anh album ${freshAlbum.index} (${images.length} anh)...`, "info", 1800);
      if (progressContext?.queueTotal) {
        const albumProgressBase = progressContext.queuePosition - 1;
        setProgress(
          `Hang doi album ${progressContext.queuePosition}/${progressContext.queueTotal}`,
          `Album ${freshAlbum.index} - dang chuan bi tai 0/${images.length} anh`,
          albumProgressBase,
          progressContext.queueTotal,
          {
            countLabel: `${progressContext.queuePosition}/${progressContext.queueTotal}`,
          }
        );
      } else {
        setProgress(
          `Dang tai album ${freshAlbum.index}`,
          `Dang chuan bi tai 0/${images.length} anh`,
          0,
          images.length
        );
      }

      for (const image of images) {
        try {
          if (button) {
            button.textContent = `Anh ${image.index}/${images.length}`;
          }
          if (progressContext?.queueTotal) {
            const queueProgress =
              progressContext.queuePosition - 1 + image.index / images.length;
            setProgress(
              `Hang doi album ${progressContext.queuePosition}/${progressContext.queueTotal}`,
              `Album ${freshAlbum.index} - anh ${image.index}/${images.length}`,
              queueProgress,
              progressContext.queueTotal,
              {
                countLabel: `${progressContext.queuePosition}/${progressContext.queueTotal}`,
              }
            );
          } else {
            setProgress(
              `Dang tai album ${freshAlbum.index}`,
              `Anh ${image.index}/${images.length}: ${image.name}`,
              image.index,
              images.length
            );
          }
          writeLog(
            `Dang tai album ${freshAlbum.index} - ${image.index}/${images.length}: ${image.name}`
          );
          await downloadImageWithRetry(image, freshAlbum.index);
        } catch (error) {
          writeLog(`Tai that bai album ${freshAlbum.index} - ${image.name}: ${error.message}`);
          showToast(`Anh ${image.index} cua album ${freshAlbum.index} loi: ${error.message}`, "error");
          failedImages.push(image.index);
        }
      }

      writeLog(`Hoan tat album ${freshAlbum.index}.`);
      if (failedImages.length) {
        showToast(
          `Album ${freshAlbum.index} xong, ${failedImages.length} anh van loi: ${failedImages.join(", ")}.`,
          "error",
          4200
        );
      } else {
        showToast(`Da tai xong album ${freshAlbum.index}.`, "success");
      }
      if (progressContext?.queueTotal) {
        setProgress(
          `Hang doi album ${progressContext.queuePosition}/${progressContext.queueTotal}`,
          failedImages.length
            ? `Album ${freshAlbum.index} xong, con ${failedImages.length} anh loi`
            : `Da tai xong album ${freshAlbum.index}`,
          progressContext.queuePosition,
          progressContext.queueTotal,
          {
            countLabel: `${progressContext.queuePosition}/${progressContext.queueTotal}`,
          }
        );
      } else {
        setProgress(
          `Dang tai album ${freshAlbum.index}`,
          failedImages.length
            ? `Hoan tat voi ${failedImages.length} anh loi: ${failedImages.join(", ")}`
            : `Da tai xong album ${freshAlbum.index}`,
          images.length,
          images.length
        );
        hideProgress();
      }

      if (button) {
        button.disabled = false;
        button.textContent = "Anh";
      }
    }

    async function downloadAlbumPdf(album, button) {
      let freshAlbum = null;

      try {
        freshAlbum = await resolveFreshAlbum(album.index);
      } catch (error) {
        writeLog(`Khong the cap nhat lai album ${album.index}: ${error.message}`);
        return;
      }

      const timestamp = Date.now();
      const images = collectImagesFromAlbum(freshAlbum.node, timestamp, freshAlbum.index);

      if (!images.length) {
        writeLog(`Album ${freshAlbum.index} hien khong co anh. Bam Lam moi roi thu lai.`);
        showToast(`Album ${freshAlbum.index} hien khong co anh.`, "error");
        return;
      }

      if (button) {
        button.disabled = true;
        button.textContent = `PDF 0/${images.length}`;
      }

      writeLog(`Bat dau tao PDF album ${freshAlbum.index} voi ${images.length} anh.`);
      showToast(`Dang tao PDF album ${freshAlbum.index}...`, "info", 1800);

      try {
        await downloadPdfFromImages(images, timestamp, freshAlbum.index, (current, total) => {
          if (button) {
            button.textContent = `PDF ${current}/${total}`;
          }
        });
        writeLog(
          `Da tai PDF album ${freshAlbum.index}: ${buildPdfFileName(timestamp, freshAlbum.index)}`
        );
        showToast(`Da tao xong PDF album ${freshAlbum.index}.`, "success", 3200);
      } catch (error) {
        writeLog(`Tao PDF that bai album ${freshAlbum.index}: ${error.message}`);
        showToast(`PDF album ${freshAlbum.index} loi: ${error.message}`, "error", 4200);
      } finally {
        if (button) {
          button.disabled = false;
          button.textContent = "PDF";
        }
      }
    }

    function clearInjectedAlbumButtons() {
      albumControls.clear();
      document
        .querySelectorAll(
          ".tm-zalo-album-actions, .tm-zalo-album-download-btn, .tm-zalo-album-pdf-btn, .tm-zalo-album-select-btn, .tm-zalo-album-select-order-badge"
        )
        .forEach((node) => {
          node.remove();
        });
      document.querySelectorAll(".tm-zalo-album-selected").forEach((node) => {
        node.classList.remove("tm-zalo-album-selected");
      });
    }

    function clearInjectedImageBadges() {
      document.querySelectorAll(".tm-zalo-image-index-badge").forEach((badge) => {
        badge.remove();
      });
    }

    function injectImageBadges(albums) {
      clearInjectedImageBadges();

      albums.forEach((album) => {
        const imageNodes = getImageNodesFromAlbum(album.node);

        imageNodes.forEach((imageNode, imageIndex) => {
          const hostNode = imageNode.parentElement || imageNode;
          if (!hostNode || !(hostNode instanceof HTMLElement)) {
            return;
          }

          if (window.getComputedStyle(hostNode).position === "static") {
            hostNode.style.position = "relative";
          }

          const badge = document.createElement("div");
          badge.className = "tm-zalo-image-index-badge";
          badge.textContent = `ab ${padAlbumIndex(album.index)} - ${padOverlayImageIndex(
            imageIndex + 1
          )}`;
          hostNode.appendChild(badge);
        });
      });
    }

    function injectAlbumButtons(albums) {
      clearInjectedAlbumButtons();
      latestAlbums = albums;

      albums.forEach((album) => {
        const albumNode = album.node;
        if (!albumNode) return;

        if (window.getComputedStyle(albumNode).position === "static") {
          albumNode.style.position = "relative";
        }

        const actions = document.createElement("div");
        actions.className = "tm-zalo-album-actions";

        const selectButton = document.createElement("button");
        selectButton.className = "tm-zalo-album-select-btn";
        selectButton.textContent = "Chon";
        selectButton.title = `Chon album ${album.index} vao hang doi tai`;

        const imageButton = document.createElement("button");
        imageButton.className = "tm-zalo-album-download-btn";
        imageButton.textContent = "Anh";
        imageButton.title = `Tai tung anh cua album ${album.index}`;

        selectButton.addEventListener("click", (event) => {
          event.preventDefault();
          event.stopPropagation();
          toggleAlbumSelection(album.index);
        });

        imageButton.addEventListener("click", async (event) => {
          event.preventDefault();
          event.stopPropagation();
          await downloadAlbum(album, imageButton);
        });

        const orderBadge = document.createElement("div");
        orderBadge.className = "tm-zalo-album-select-order-badge";
        orderBadge.hidden = true;

        actions.appendChild(selectButton);
        actions.appendChild(imageButton);
        albumNode.appendChild(orderBadge);
        albumNode.appendChild(actions);
        albumControls.set(album.index, { albumNode, selectButton, imageButton, orderBadge });
      });

      updateAlbumControls();
    }

    async function downloadSelectedAlbums() {
      if (isQueueDownloading) {
        return;
      }

      const queue = selectedAlbumIndexes.map((albumIndex) => ({ index: albumIndex }));
      if (!queue.length) {
        showToast("Chua chon album nao.", "error");
        return;
      }

      isQueueDownloading = true;
      queueButton.textContent = `Hang doi 0/${queue.length}`;
      writeLog(`Bat dau tai hang doi ${queue.length} album: ${queue.map((album) => album.index).join(", ")}.`);
      setProgress("Hang doi album", `Dang chuan bi tai ${queue.length} album da chon`, 0, queue.length);
      updateAlbumControls();

      try {
        for (let i = 0; i < queue.length; i += 1) {
          const album = queue[i];
          queueButton.textContent = `Hang doi ${i + 1}/${queue.length}`;
          queueButton.title = `Dang tai album ${album.index} theo thu tu da chon`;
          showToast(`Dang tai album ${album.index} (${i + 1}/${queue.length})...`, "info", 1800);
          await downloadAlbum(album, null, { queuePosition: i + 1, queueTotal: queue.length });
        }

        writeLog(`Hoan tat tai hang doi ${queue.length} album.`);
        showToast(`Da tai xong ${queue.length} album da chon.`, "success", 3200);
        setProgress("Hang doi album", `Da tai xong ${queue.length} album da chon`, queue.length, queue.length);
        hideProgress();
      } finally {
        isQueueDownloading = false;
        updateAlbumControls();
      }
    }

    async function refreshAlbums() {
      const xpath = DEFAULT_ALBUM_XPATH;

      if (!xpath) {
        clearInjectedAlbumButtons();
        clearInjectedImageBadges();
        writeLog("Chua nhap XPath.");
        return [];
      }

      try {
        await sleep(500);
        const albums = collectAlbums(xpath);
        const totalImages = albums.reduce((sum, album) => sum + album.images.length, 0);
        trimSelectedAlbums(albums);
        injectAlbumButtons(albums);
        injectImageBadges(albums);
        writeLog(`Lam moi xong: ${albums.length} album, ${totalImages} anh dang duoc load.`);
        showRefreshSummary(albums.length, totalImages);
        updateAlbumControls();
        return albums;
      } catch (error) {
        clearInjectedAlbumButtons();
        clearInjectedImageBadges();
        latestAlbums = [];
        writeLog(`Lam moi that bai: ${error.message}`);
        showToast(`Lam moi that bai: ${error.message}`, "error", 3200);
        setRefreshLabel("Co loi", error.message);
        updateQueueButton();
        return [];
      }
    }

    refreshButton.addEventListener("click", async () => {
      if (isQueueDownloading) {
        return;
      }
      writeLog("Dang lam moi danh sach album va anh...");
      refreshButton.disabled = true;
      setRefreshLabel("Dang quet...", "Dang quet lai album dang load");
      try {
        await refreshAlbums();
      } finally {
        refreshButton.disabled = false;
        if (refreshButton.textContent === "Dang quet...") {
          setRefreshLabel("Lam moi", "Lam moi de quet lai cac album dang duoc load");
        }
      }
    });

    queueButton.addEventListener("click", async () => {
      await downloadSelectedAlbums();
    });

    document.body.appendChild(refreshButton);
    document.body.appendChild(queueButton);
    document.body.appendChild(progressPanel);
    document.body.appendChild(toastContainer);
    updateQueueButton();
    syncRefreshButtonState();
    refreshAlbums();
  }

  async function bootstrap() {
    await waitForBody();
    await waitForDocumentComplete();
    await waitForPageToSettle();
    createPanel();
  }

  bootstrap();
})();
