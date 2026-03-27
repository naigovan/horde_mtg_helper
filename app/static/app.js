const DEFAULT_ANIMATION_MS = 460;
const TAP_ANIMATION_MS = 340;
const MENU_OWNER_SELECTOR = ".battle-card, .board-zone-card.card";
const MENU_TRIGGER_SELECTOR = "[data-menu-trigger]";
const ZONE_CARD_SELECTOR = ".board-zone-card.card";
const ZONE_PANEL_SELECTOR = ".zone-hover-panel";
const ZONE_TRIGGER_SELECTOR = ".board-zone-card-surface, .board-zone-mini-face";
const ZONE_PANEL_ROOT_SELECTOR = "[data-zone-panel-root]";
const ZONE_PANEL_HIDE_DELAY_MS = 140;
const MOBILE_ZONE_PANEL_BREAKPOINT = 1360;

let zonePanelPositionFrame = 0;
let zonePanelPositioningInstalled = false;
const zonePanelVisibilityState = new Map();

function parseGameState(root = document) {
  const scope = root instanceof Document ? root : root.ownerDocument || document;
  const container = root instanceof Document ? scope : root;
  const stateNode = container.querySelector("[data-game-state-json]");
  if (!stateNode) {
    return null;
  }

  try {
    return JSON.parse(stateNode.textContent || "{}");
  } catch (_error) {
    return null;
  }
}

function buildCardIndex(state) {
  const index = new Map();
  if (!state || !Array.isArray(state.cards)) {
    return index;
  }

  for (const card of state.cards) {
    index.set(String(card.id), card);
  }
  return index;
}

function summarizeGameState(state) {
  const liveBattlefieldNote = getLiveBattlefieldNote();
  if (!state) {
    return {
      coordinateSystem: "DOM layout; origin is the top-left of the page, x increases right, y increases down.",
      mode: "unknown",
      battlefieldNote: liveBattlefieldNote,
    };
  }

  const zoneCards = {
    battlefield: [],
    graveyard: [],
    exile: [],
    commander: [],
  };
  const battlefieldStacks = new Map();

  for (const card of state.cards || []) {
    if (zoneCards[card.zone]) {
      zoneCards[card.zone].push({
        id: card.id,
        name: card.name,
        tapped: Boolean(card.tapped),
        phasedOut: Boolean(card.phasedOut),
        note: card.note || "",
      });
    }

    if (card.zone === "battlefield") {
      const stackKey = card.stackKey || String(card.id);
      if (!battlefieldStacks.has(stackKey)) {
        battlefieldStacks.set(stackKey, {
          key: stackKey,
          name: card.name,
          count: 0,
          tapped: Boolean(card.tapped),
          phasedOut: Boolean(card.phasedOut),
          note: card.note || "",
        });
      }
      battlefieldStacks.get(stackKey).count += 1;
    }
  }

  return {
    coordinateSystem: "DOM layout; origin is the top-left of the page, x increases right, y increases down.",
    mode: "active_game",
    gameId: state.gameId,
    name: state.name,
    turn: state.turn,
    wave: state.wave,
    latestAction: state.latestAction,
    battlefieldNote: liveBattlefieldNote || state.battlefieldNote || "",
    counts: state.counts,
    battlefield: zoneCards.battlefield,
    battlefieldStacks: Array.from(battlefieldStacks.values()),
    graveyard: zoneCards.graveyard,
    exile: zoneCards.exile,
    commander: zoneCards.commander,
  };
}

function getBattlefieldNoteStorageKey(root = document) {
  const page = root.querySelector("[data-game-page]");
  const gameId = page instanceof HTMLElement ? page.dataset.gameId : "";
  if (!gameId) {
    return null;
  }
  return `mtg-horde:battlefield-note:${gameId}`;
}

function getBattlefieldNoteInput(root = document) {
  return root.querySelector(".battlefield-note-form input[name='note']");
}

function getLiveBattlefieldNote(root = document) {
  const input = getBattlefieldNoteInput(root);
  return input instanceof HTMLInputElement ? input.value : "";
}

function restoreBattlefieldNote(root = document) {
  const input = getBattlefieldNoteInput(root);
  const storageKey = getBattlefieldNoteStorageKey(root);
  if (!(input instanceof HTMLInputElement) || !storageKey) {
    return;
  }

  try {
    const stored = window.localStorage.getItem(storageKey);
    if (stored !== null && input.value !== stored) {
      input.value = stored;
    }
  } catch (_error) {
    // Ignore storage access issues and leave the server-rendered value in place.
  }
}

function persistBattlefieldNote(root = document) {
  const input = getBattlefieldNoteInput(root);
  const storageKey = getBattlefieldNoteStorageKey(root);
  if (!(input instanceof HTMLInputElement) || !storageKey) {
    return;
  }

  try {
    const value = input.value || "";
    if (value) {
      window.localStorage.setItem(storageKey, value);
    } else {
      window.localStorage.removeItem(storageKey);
    }
  } catch (_error) {
    // Ignore storage access issues and keep the UI responsive.
  }
}

function installTestingHooks() {
  restoreBattlefieldNote(document);
  window.render_game_to_text = () => JSON.stringify(summarizeGameState(parseGameState(document)));
  window.advanceTime = (ms) =>
    new Promise((resolve) => {
      const start = performance.now();

      function step(now) {
        if (now - start >= ms) {
          resolve();
          return;
        }
        window.requestAnimationFrame(step);
      }

      window.requestAnimationFrame(step);
    });
}

function isMenuOwner(element) {
  return element instanceof Element && element.matches(MENU_OWNER_SELECTOR);
}

function getMenuOwner(element) {
  if (!(element instanceof Element)) {
    return null;
  }

  const directOwner = element.closest(MENU_OWNER_SELECTOR);
  if (directOwner) {
    return directOwner;
  }

  const floatingPanel = element.closest(`${ZONE_PANEL_SELECTOR}[data-owner-id]`);
  if (!(floatingPanel instanceof HTMLElement)) {
    return null;
  }

  const ownerId = floatingPanel.dataset.ownerId || "";
  return ownerId ? document.getElementById(ownerId) : null;
}

function isZoneCard(element) {
  return element instanceof Element && element.matches(ZONE_CARD_SELECTOR);
}

function getZonePanelState(ownerId) {
  if (!zonePanelVisibilityState.has(ownerId)) {
    zonePanelVisibilityState.set(ownerId, {
      ownerHovered: false,
      panelHovered: false,
      hideTimer: 0,
    });
  }

  return zonePanelVisibilityState.get(ownerId);
}

function clearZonePanelHideTimer(ownerId) {
  const state = getZonePanelState(ownerId);
  if (state.hideTimer) {
    window.clearTimeout(state.hideTimer);
    state.hideTimer = 0;
  }
}

function setZonePanelHoverState(ownerId, key, value) {
  const state = getZonePanelState(ownerId);
  state[key] = value;

  if (value) {
    clearZonePanelHideTimer(ownerId);
    scheduleZonePanelPositionUpdate();
    return;
  }

  if (state.ownerHovered || state.panelHovered) {
    scheduleZonePanelPositionUpdate();
    return;
  }

  clearZonePanelHideTimer(ownerId);
  state.hideTimer = window.setTimeout(() => {
    state.hideTimer = 0;
    scheduleZonePanelPositionUpdate();
  }, ZONE_PANEL_HIDE_DELAY_MS);
}

function ensureZonePanelRoot() {
  const page = document.querySelector("[data-game-page]");
  if (!(page instanceof HTMLElement)) {
    return null;
  }

  let root = page.querySelector(ZONE_PANEL_ROOT_SELECTOR);
  if (!(root instanceof HTMLElement)) {
    root = document.createElement("div");
    root.className = "zone-panel-root";
    root.setAttribute("data-zone-panel-root", "");
    page.append(root);
  }

  return root;
}

function getZonePanelOwner(panel) {
  if (!(panel instanceof HTMLElement)) {
    return null;
  }

  const ownerId = panel.dataset.ownerId || "";
  if (ownerId) {
    return document.getElementById(ownerId);
  }

  return panel.closest(ZONE_CARD_SELECTOR);
}

function bindZonePanelOwner(owner) {
  if (!(owner instanceof HTMLElement) || !owner.id || owner.dataset.zonePanelOwnerBound === "true") {
    return;
  }

  owner.dataset.zonePanelOwnerBound = "true";
  const ownerId = owner.id;

  owner.addEventListener("pointerenter", () => {
    setZonePanelHoverState(ownerId, "ownerHovered", true);
  });

  owner.addEventListener("pointerleave", () => {
    setZonePanelHoverState(ownerId, "ownerHovered", false);
  });

  owner.addEventListener("focusin", () => {
    scheduleZonePanelPositionUpdate();
  });

  owner.addEventListener("focusout", () => {
    window.requestAnimationFrame(scheduleZonePanelPositionUpdate);
  });
}

function bindZonePanel(panel) {
  if (!(panel instanceof HTMLElement) || panel.dataset.zonePanelBound === "true") {
    return;
  }

  panel.dataset.zonePanelBound = "true";
  const ownerId = panel.dataset.ownerId || "";
  if (!ownerId) {
    return;
  }

  panel.addEventListener("pointerenter", () => {
    setZonePanelHoverState(ownerId, "panelHovered", true);
  });

  panel.addEventListener("pointerleave", () => {
    setZonePanelHoverState(ownerId, "panelHovered", false);
  });

  panel.addEventListener("focusin", () => {
    scheduleZonePanelPositionUpdate();
  });

  panel.addEventListener("focusout", () => {
    window.requestAnimationFrame(scheduleZonePanelPositionUpdate);
  });
}

function mountZonePanels() {
  const root = ensureZonePanelRoot();
  if (!(root instanceof HTMLElement)) {
    return;
  }

  for (const owner of document.querySelectorAll(ZONE_CARD_SELECTOR)) {
    if (!(owner instanceof HTMLElement) || !owner.id) {
      continue;
    }

    bindZonePanelOwner(owner);

    const panel = owner.querySelector(ZONE_PANEL_SELECTOR);
    if (!(panel instanceof HTMLElement)) {
      continue;
    }

    panel.dataset.ownerId = owner.id;
    if (panel.parentElement !== root) {
      root.append(panel);
    }

    bindZonePanel(panel);
  }
}

function shouldShowZonePanel(owner, panel) {
  if (!(owner instanceof HTMLElement) || !(panel instanceof HTMLElement)) {
    return false;
  }

  const state = getZonePanelState(owner.id);
  return (
    state.ownerHovered ||
    state.panelHovered ||
    owner.classList.contains("is-menu-pinned") ||
    owner.matches(":focus-within") ||
    panel.matches(":focus-within")
  );
}

function scheduleZonePanelPositionUpdate() {
  if (zonePanelPositionFrame) {
    window.cancelAnimationFrame(zonePanelPositionFrame);
  }

  zonePanelPositionFrame = window.requestAnimationFrame(() => {
    zonePanelPositionFrame = 0;
    updateZonePanelPositions();
  });
}

function getZonePanelPlacement(triggerRect, panelRect) {
  const margin = 16;
  const gap = 16;
  const panelWidth = Math.min(panelRect.width || 0, window.innerWidth - margin * 2);
  const panelHeight = Math.min(panelRect.height || 0, window.innerHeight - margin * 2);

  if (window.innerWidth <= MOBILE_ZONE_PANEL_BREAKPOINT) {
    const topCandidate = triggerRect.top - panelHeight - gap;
    const bottomCandidate = triggerRect.bottom + gap;
    const fitsAbove = topCandidate >= margin;
    const fitsBelow = bottomCandidate + panelHeight <= window.innerHeight - margin;
    const position = fitsAbove || !fitsBelow ? "top" : "bottom";
    const top = position === "top" ? topCandidate : bottomCandidate;
    const left = Math.min(
      window.innerWidth - margin - panelWidth,
      Math.max(margin, triggerRect.right - panelWidth),
    );
    return { position, top: Math.max(margin, Math.min(top, window.innerHeight - margin - panelHeight)), left };
  }

  const rightCandidate = triggerRect.right + gap;
  const leftCandidate = triggerRect.left - panelWidth - gap;
  const fitsRight = rightCandidate + panelWidth <= window.innerWidth - margin;
  const fitsLeft = leftCandidate >= margin;
  const position = fitsRight || !fitsLeft ? "right" : "left";
  const left = position === "right" ? rightCandidate : leftCandidate;
  const centeredTop = triggerRect.top + (triggerRect.height - panelHeight) / 2;
  const top = Math.max(margin, Math.min(centeredTop, window.innerHeight - margin - panelHeight));
  return { position, top, left };
}

function positionZonePanel(panel) {
  if (!(panel instanceof HTMLElement)) {
    return;
  }

  const owner = getZonePanelOwner(panel);
  if (!isZoneCard(owner)) {
    return;
  }

  const trigger = owner.querySelector(ZONE_TRIGGER_SELECTOR);
  if (!(trigger instanceof HTMLElement)) {
    return;
  }

  const triggerRect = trigger.getBoundingClientRect();
  const panelRect = panel.getBoundingClientRect();
  const { position, top, left } = getZonePanelPlacement(triggerRect, panelRect);
  panel.dataset.panelPosition = position;
  panel.style.top = `${Math.round(top)}px`;
  panel.style.left = `${Math.round(left)}px`;
}

function updateZonePanelPositions() {
  mountZonePanels();

  for (const panel of document.querySelectorAll(`${ZONE_PANEL_ROOT_SELECTOR} ${ZONE_PANEL_SELECTOR}`)) {
    if (!(panel instanceof HTMLElement)) {
      continue;
    }

    const owner = getZonePanelOwner(panel);
    if (!isZoneCard(owner)) {
      continue;
    }

    const visible = shouldShowZonePanel(owner, panel);
    panel.classList.toggle("is-visible", visible);
    panel.setAttribute("aria-hidden", visible ? "false" : "true");

    if (visible) {
      positionZonePanel(panel);
    }
  }
}

function installZonePanelPositioning() {
  mountZonePanels();

  if (!zonePanelPositioningInstalled) {
    zonePanelPositioningInstalled = true;

    window.addEventListener("resize", scheduleZonePanelPositionUpdate);
    window.addEventListener("scroll", scheduleZonePanelPositionUpdate, { passive: true });

    document.addEventListener(
      "pointerenter",
      (event) => {
        const target = event.target;
        if (target instanceof Element && (target.closest(ZONE_CARD_SELECTOR) || target.closest(ZONE_PANEL_SELECTOR))) {
          scheduleZonePanelPositionUpdate();
        }
      },
      true,
    );

    document.addEventListener("focusin", (event) => {
      const target = event.target;
      if (target instanceof Element && (target.closest(ZONE_CARD_SELECTOR) || target.closest(ZONE_PANEL_SELECTOR))) {
        scheduleZonePanelPositionUpdate();
      }
    });

    document.addEventListener("click", (event) => {
      const target = event.target;
      if (target instanceof Element && (target.closest(ZONE_CARD_SELECTOR) || target.closest(ZONE_PANEL_SELECTOR))) {
        scheduleZonePanelPositionUpdate();
      }
    });
  }

  scheduleZonePanelPositionUpdate();
}

function setMenuPinned(owner, pinned) {
  if (!isMenuOwner(owner)) {
    return;
  }
  owner.classList.toggle("is-menu-pinned", pinned);
  if (owner instanceof HTMLElement) {
    owner.setAttribute("aria-expanded", pinned ? "true" : "false");
  }
  scheduleZonePanelPositionUpdate();
}

function clearPinnedMenus(exceptOwner = null) {
  for (const owner of document.querySelectorAll(`${MENU_OWNER_SELECTOR}.is-menu-pinned`)) {
    if (exceptOwner && owner === exceptOwner) {
      continue;
    }
    setMenuPinned(owner, false);
  }
}

function installMenuPinning() {
  installZonePanelPositioning();
  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }

    if (!target.closest("[data-game-page]")) {
      clearPinnedMenus();
      return;
    }

    const owner = getMenuOwner(target);
    const interactiveTarget = target.closest("button, input, textarea, select, a, label");
    const trigger = target.closest(MENU_TRIGGER_SELECTOR);

    if (interactiveTarget && owner) {
      clearPinnedMenus(owner);
      setMenuPinned(owner, true);
      return;
    }

    if (trigger) {
      const triggerOwner = getMenuOwner(trigger);
      if (!triggerOwner) {
        return;
      }

      const nextPinned = !triggerOwner.classList.contains("is-menu-pinned");
      clearPinnedMenus(nextPinned ? triggerOwner : null);
      setMenuPinned(triggerOwner, nextPinned);
      if (nextPinned && triggerOwner instanceof HTMLElement) {
        triggerOwner.focus({ preventScroll: true });
      }
      return;
    }

    if (owner) {
      clearPinnedMenus(owner);
      setMenuPinned(owner, true);
      return;
    }

    clearPinnedMenus();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") {
      return;
    }
    clearPinnedMenus();
  });
}

function rectToPlain(rect) {
  return {
    left: rect.left,
    top: rect.top,
    width: rect.width,
    height: rect.height,
    right: rect.right,
    bottom: rect.bottom,
  };
}

function getLayoutKeyForCard(card) {
  if (!card) {
    return "";
  }
  return card.zone === "battlefield" && card.stackKey ? String(card.stackKey) : String(card.id);
}

function getNormalizedAnchorRect(element) {
  const rect = rectToPlain(element.getBoundingClientRect());
  const width = Math.min(Math.max(rect.width * 0.42, 92), 156);
  const height = Math.min(Math.max(width * 1.4, 128), 220);
  const left = rect.left + (rect.width - width) / 2;
  const top = rect.top + (rect.height - height) / 2;
  return {
    left,
    top,
    width,
    height,
    right: left + width,
    bottom: top + height,
  };
}

function snapshotLayout(root = document) {
  const cards = new Map();
  const cardsById = new Map();
  const anchors = new Map();

  for (const element of root.querySelectorAll("[data-card-node='card']")) {
    const layoutKey = element.dataset.stackKey || element.dataset.cardId;
    const cardId = element.dataset.cardId;
    if (!cardId || !layoutKey) {
      continue;
    }
    const snapshot = {
      element,
      cardId,
      stackKey: element.dataset.stackKey || "",
      stackCount: Number.parseInt(element.dataset.stackCount || "1", 10) || 1,
      zone: element.dataset.zone || "",
      tapped: element.dataset.tapped === "true",
      rect: rectToPlain(element.getBoundingClientRect()),
    };
    cards.set(layoutKey, snapshot);
    cardsById.set(cardId, snapshot);
  }

  for (const anchor of root.querySelectorAll("[data-zone-anchor]")) {
    const zone = anchor.dataset.zoneAnchor;
    if (!zone) {
      continue;
    }
    anchors.set(zone, {
      element: anchor,
      rect: getNormalizedAnchorRect(anchor),
    });
  }

  return { cards, cardsById, anchors };
}

function getActionMeta(form) {
  const actionPath = new URL(form.action, window.location.origin).pathname;
  const flagName = form.querySelector('input[name="flag_name"]')?.value || "";
  return {
    actionPath,
    actingCardId: form.dataset.cardId || "",
    instantTap: actionPath.endsWith("/tap-all") || actionPath.endsWith("/untap-all"),
    singleTapToggle: actionPath.includes("/toggle") && flagName === "tapped",
  };
}

function afterTwoFrames(callback) {
  window.requestAnimationFrame(() => {
    window.requestAnimationFrame(callback);
  });
}

function animateElementFromRect(element, fromRect, duration = DEFAULT_ANIMATION_MS) {
  if (!fromRect || !element) {
    return;
  }

  const toRect = rectToPlain(element.getBoundingClientRect());
  if (!toRect.width || !toRect.height) {
    return;
  }

  const deltaX = fromRect.left - toRect.left;
  const deltaY = fromRect.top - toRect.top;
  const scaleX = fromRect.width / toRect.width;
  const scaleY = fromRect.height / toRect.height;
  const isStationary =
    Math.abs(deltaX) < 1 &&
    Math.abs(deltaY) < 1 &&
    Math.abs(scaleX - 1) < 0.01 &&
    Math.abs(scaleY - 1) < 0.01;

  if (isStationary) {
    return;
  }

  element.classList.add("is-animating");
  element.style.transition = "none";
  element.style.transformOrigin = "top left";
  element.style.opacity = "0.72";
  element.style.transform = `translate(${deltaX}px, ${deltaY}px) scale(${scaleX}, ${scaleY})`;

  afterTwoFrames(() => {
    element.style.transition = `transform ${duration}ms cubic-bezier(0.18, 0.84, 0.22, 1), opacity ${Math.round(
      duration * 0.8
    )}ms ease`;
    element.style.transform = "";
    element.style.opacity = "";

    window.setTimeout(() => {
      element.classList.remove("is-animating");
      element.style.transition = "";
      element.style.transformOrigin = "";
      element.style.transform = "";
      element.style.opacity = "";
    }, duration + 40);
  });
}

function buildGhostNode(sourceElement, rect) {
  const ghost = sourceElement.cloneNode(true);
  ghost.classList.add("card-ghost");
  ghost.querySelectorAll("form, button, input, textarea, select").forEach((element) => element.remove());
  ghost
    .querySelectorAll(".battle-card-controls, .battle-card-menu, .zone-hover-panel, .battle-card-stack-layers, .battle-card-stack-count")
    .forEach((element) => element.remove());

  ghost.style.position = "fixed";
  ghost.style.left = `${rect.left}px`;
  ghost.style.top = `${rect.top}px`;
  ghost.style.width = `${rect.width}px`;
  ghost.style.height = `${rect.height}px`;
  ghost.style.margin = "0";
  ghost.style.pointerEvents = "none";
  ghost.style.zIndex = "1000";
  return ghost;
}

function animateGhostFromRect(element, fromRect, targetRect, duration = DEFAULT_ANIMATION_MS) {
  if (!element || !fromRect || !targetRect) {
    return;
  }

  const ghost = buildGhostNode(element, fromRect);
  document.body.appendChild(ghost);

  const deltaX = targetRect.left - fromRect.left;
  const deltaY = targetRect.top - fromRect.top;
  const scaleX = targetRect.width / Math.max(fromRect.width, 1);
  const scaleY = targetRect.height / Math.max(fromRect.height, 1);

  afterTwoFrames(() => {
    ghost.style.transition = `transform ${duration}ms cubic-bezier(0.2, 0.8, 0.22, 1), opacity ${duration}ms ease`;
    ghost.style.transformOrigin = "top left";
    ghost.style.transform = `translate(${deltaX}px, ${deltaY}px) scale(${scaleX}, ${scaleY})`;
    ghost.style.opacity = "0.14";
  });

  window.setTimeout(() => {
    ghost.remove();
  }, duration + 70);
}

function getSnapshotForCard(layout, card) {
  if (!layout || !card) {
    return null;
  }
  const layoutKey = getLayoutKeyForCard(card);
  return layout.cards.get(layoutKey) || layout.cardsById.get(String(card.id)) || null;
}

function animateStackCountChange(element, previousCount, nextCount) {
  if (!element || previousCount === nextCount) {
    return;
  }

  const badge = element.querySelector(".battle-card-stack-count");
  if (!badge) {
    return;
  }

  badge.classList.remove("is-bumping");
  void badge.offsetWidth;
  badge.classList.add("is-bumping");

  window.setTimeout(() => {
    badge.classList.remove("is-bumping");
  }, 380);
}

function animateTapState(element, previousTapped, nextTapped) {
  if (!element || previousTapped === nextTapped) {
    return;
  }

  const art = element.querySelector(".battle-card-art");
  if (!art) {
    return;
  }

  const tappedTransform = "rotate(90deg) scale(0.78)";
  const fromTransform = previousTapped ? tappedTransform : "rotate(0deg) scale(1)";
  const toTransform = nextTapped ? tappedTransform : "rotate(0deg) scale(1)";

  art.style.transition = "none";
  art.style.transform = fromTransform;

  afterTwoFrames(() => {
    art.style.transition = `transform ${TAP_ANIMATION_MS}ms cubic-bezier(0.22, 0.82, 0.2, 1)`;
    art.style.transform = toTransform;

    window.setTimeout(() => {
      art.style.transition = "";
      art.style.transform = "";
    }, TAP_ANIMATION_MS + 40);
  });
}

function animateGameTransition(previousLayout, previousState, nextState, actionMeta) {
  const nextLayout = snapshotLayout(document);
  const previousCards = buildCardIndex(previousState);
  const nextCards = buildCardIndex(nextState);

  for (const [layoutKey, nextSnapshot] of nextLayout.cards.entries()) {
    const previousSnapshot = previousLayout.cards.get(layoutKey);
    const previousCard = previousCards.get(nextSnapshot.cardId);
    const nextCard = nextCards.get(nextSnapshot.cardId);

    if (previousSnapshot) {
      animateElementFromRect(nextSnapshot.element, previousSnapshot.rect);
      animateStackCountChange(nextSnapshot.element, previousSnapshot.stackCount, nextSnapshot.stackCount);
    } else if (previousCard) {
      const previousVisibleSnapshot = previousCard.zone === "battlefield" ? getSnapshotForCard(previousLayout, previousCard) : null;
      const sourceAnchor = previousLayout.anchors.get(previousCard.zone);
      if (previousVisibleSnapshot) {
        animateElementFromRect(nextSnapshot.element, previousVisibleSnapshot.rect);
      } else if (sourceAnchor) {
        animateElementFromRect(nextSnapshot.element, sourceAnchor.rect);
      }
    }

    if (
      !actionMeta.instantTap &&
      actionMeta.singleTapToggle &&
      actionMeta.actingCardId &&
      previousCard &&
      nextCard &&
      previousCard.zone === "battlefield" &&
      nextCard.zone === "battlefield" &&
      (nextSnapshot.cardId === actionMeta.actingCardId || previousSnapshot?.cardId === actionMeta.actingCardId)
    ) {
      animateTapState(nextSnapshot.element, Boolean(previousCard.tapped), Boolean(nextCard.tapped));
    }
  }

  for (const [cardId, nextCard] of nextCards.entries()) {
    const previousCard = previousCards.get(cardId);
    if (!previousCard) {
      continue;
    }

    const zoneChanged = previousCard.zone !== nextCard.zone;
    const stackChanged =
      previousCard.zone === "battlefield" &&
      nextCard.zone === "battlefield" &&
      previousCard.stackKey !== nextCard.stackKey;

    if (!zoneChanged && !stackChanged) {
      continue;
    }

    const previousSnapshot = getSnapshotForCard(previousLayout, previousCard);
    const nextSnapshot = getSnapshotForCard(nextLayout, nextCard);
    const previousAnchor = previousLayout.anchors.get(previousCard.zone);
    const nextAnchor = nextLayout.anchors.get(nextCard.zone);
    const nextLayoutKey = getLayoutKeyForCard(nextCard);
    const previousLayoutKey = getLayoutKeyForCard(previousCard);

    if (zoneChanged) {
      if (previousCard.zone === "battlefield" && previousSnapshot && nextAnchor) {
        animateGhostFromRect(previousSnapshot.element, previousSnapshot.rect, nextAnchor.rect);
      }

      if (
        previousCard.zone !== "battlefield" &&
        nextCard.zone === "battlefield" &&
        nextSnapshot &&
        previousAnchor &&
        previousLayout.cards.has(nextLayoutKey)
      ) {
        animateGhostFromRect(nextSnapshot.element, previousAnchor.rect, nextSnapshot.rect);
      }
      continue;
    }

    if (
      stackChanged &&
      previousSnapshot &&
      nextSnapshot &&
      (previousLayout.cards.has(nextLayoutKey) || nextLayout.cards.has(previousLayoutKey))
    ) {
      animateGhostFromRect(nextSnapshot.element, previousSnapshot.rect, nextSnapshot.rect);
    }
  }
}

function syncDocumentState(doc, response) {
  const nextPath = new URL(response.url, window.location.origin);
  const nextRelativePath = `${nextPath.pathname}${nextPath.search}`;
  const currentRelativePath = `${window.location.pathname}${window.location.search}`;
  const currentScrollY = window.scrollY;

  document.title = doc.title || document.title;

  if (nextRelativePath !== currentRelativePath) {
    window.history.pushState({}, "", nextRelativePath);
    window.scrollTo({ top: 0, behavior: "auto" });
    return;
  }

  window.scrollTo({ top: currentScrollY, behavior: "auto" });
}

document.addEventListener("submit", async (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) {
    return;
  }

  if (form.matches(".battlefield-note-form")) {
    event.preventDefault();
    persistBattlefieldNote(document);
    return;
  }

  if (form.method.toLowerCase() !== "post") {
    return;
  }

  if (!form.closest("[data-game-page]")) {
    return;
  }

  if (form.dataset.fullReload === "true") {
    return;
  }

  event.preventDefault();

  const submitter = event.submitter instanceof HTMLElement ? event.submitter : null;
  if (submitter) {
    submitter.setAttribute("disabled", "disabled");
  }

  const actionMeta = getActionMeta(form);
  const previousLayout = snapshotLayout(document);
  const previousState = parseGameState(document);

  try {
    const response = await fetch(form.action, {
      method: "POST",
      body: new FormData(form),
      headers: {
        "X-Requested-With": "fetch",
      },
      redirect: "follow",
    });

    const html = await response.text();
    const parser = new DOMParser();
    const doc = parser.parseFromString(html, "text/html");
    const newMain = doc.querySelector("main.page-shell");

    if (!newMain) {
      window.location.href = response.url;
      return;
    }

    const currentMain = document.querySelector("main.page-shell");
    if (!currentMain) {
      window.location.href = response.url;
      return;
    }

    currentMain.innerHTML = newMain.innerHTML;
    installTestingHooks();
    installZonePanelPositioning();
    animateGameTransition(previousLayout, previousState, parseGameState(document), actionMeta);
    syncDocumentState(doc, response);
  } catch (_error) {
    form.submit();
  } finally {
    if (submitter) {
      submitter.removeAttribute("disabled");
    }
  }
});

document.addEventListener("input", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement)) {
    return;
  }

  if (!target.matches(".battlefield-note-form input[name='note']")) {
    return;
  }

  persistBattlefieldNote(document);
});

document.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof Element)) {
    return;
  }

  const button = target.closest(".battlefield-note-form button");
  if (!(button instanceof HTMLButtonElement)) {
    return;
  }

  event.preventDefault();
  persistBattlefieldNote(document);
});

window.addEventListener("DOMContentLoaded", installTestingHooks);
window.addEventListener("DOMContentLoaded", installMenuPinning);
