const DEFAULT_ANIMATION_MS = 460;
const TAP_ANIMATION_MS = 340;

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
  if (!state) {
    return {
      coordinateSystem: "DOM layout; origin is the top-left of the page, x increases right, y increases down.",
      mode: "unknown",
    };
  }

  const zoneCards = {
    battlefield: [],
    graveyard: [],
    exile: [],
    commander: [],
  };

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
  }

  return {
    coordinateSystem: "DOM layout; origin is the top-left of the page, x increases right, y increases down.",
    mode: "active_game",
    gameId: state.gameId,
    name: state.name,
    turn: state.turn,
    wave: state.wave,
    latestAction: state.latestAction,
    counts: state.counts,
    battlefield: zoneCards.battlefield,
    graveyard: zoneCards.graveyard,
    exile: zoneCards.exile,
    commander: zoneCards.commander,
  };
}

function installTestingHooks() {
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
  const anchors = new Map();

  for (const element of root.querySelectorAll("[data-card-id]")) {
    const cardId = element.dataset.cardId;
    if (!cardId) {
      continue;
    }
    cards.set(cardId, {
      element,
      zone: element.dataset.zone || "",
      tapped: element.dataset.tapped === "true",
      rect: rectToPlain(element.getBoundingClientRect()),
    });
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

  return { cards, anchors };
}

function getActionMeta(form) {
  const actionPath = new URL(form.action, window.location.origin).pathname;
  const flagName = form.querySelector('input[name="flag_name"]')?.value || "";
  return {
    actionPath,
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
  const controls = ghost.querySelector(".battle-card-controls");
  if (controls) {
    controls.remove();
  }

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

function animateGhostToRect(sourceSnapshot, targetRect, duration = DEFAULT_ANIMATION_MS) {
  if (!sourceSnapshot || !targetRect) {
    return;
  }

  const ghost = buildGhostNode(sourceSnapshot.element, sourceSnapshot.rect);
  document.body.appendChild(ghost);

  const deltaX = targetRect.left - sourceSnapshot.rect.left;
  const deltaY = targetRect.top - sourceSnapshot.rect.top;
  const scaleX = targetRect.width / Math.max(sourceSnapshot.rect.width, 1);
  const scaleY = targetRect.height / Math.max(sourceSnapshot.rect.height, 1);

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

function animateTapState(element, previousTapped, nextTapped) {
  if (!element || previousTapped === nextTapped) {
    return;
  }

  const art = element.querySelector(".battle-card-art");
  if (!art) {
    return;
  }

  const fromTransform = previousTapped ? "rotate(90deg) scale(0.72)" : "rotate(0deg) scale(1)";
  const toTransform = nextTapped ? "rotate(90deg) scale(0.72)" : "rotate(0deg) scale(1)";

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

  for (const [cardId, nextSnapshot] of nextLayout.cards.entries()) {
    const previousSnapshot = previousLayout.cards.get(cardId);
    const previousCard = previousCards.get(cardId);
    const nextCard = nextCards.get(cardId);

    if (previousSnapshot) {
      animateElementFromRect(nextSnapshot.element, previousSnapshot.rect);
    } else if (previousCard) {
      const sourceAnchor = previousLayout.anchors.get(previousCard.zone);
      if (sourceAnchor) {
        animateElementFromRect(nextSnapshot.element, sourceAnchor.rect);
      }
    }

    if (
      !actionMeta.instantTap &&
      actionMeta.singleTapToggle &&
      previousCard &&
      nextCard &&
      previousCard.zone === "battlefield" &&
      nextCard.zone === "battlefield"
    ) {
      animateTapState(nextSnapshot.element, Boolean(previousCard.tapped), Boolean(nextCard.tapped));
    }
  }

  for (const [cardId, previousSnapshot] of previousLayout.cards.entries()) {
    if (nextLayout.cards.has(cardId)) {
      continue;
    }

    const nextCard = nextCards.get(cardId);
    if (!nextCard) {
      continue;
    }

    const targetAnchor = nextLayout.anchors.get(nextCard.zone);
    if (targetAnchor) {
      animateGhostToRect(previousSnapshot, targetAnchor.rect);
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

  if (form.method.toLowerCase() !== "post") {
    return;
  }

  if (!form.closest("[data-game-page]")) {
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

window.addEventListener("DOMContentLoaded", installTestingHooks);
