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

  const currentPath = window.location.pathname + window.location.search;
  const currentScrollY = window.scrollY;

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

    const nextPath = new URL(response.url, window.location.origin);
    const nextRelativePath = `${nextPath.pathname}${nextPath.search}`;

    document.title = doc.title || document.title;
    const currentMain = document.querySelector("main.page-shell");
    if (currentMain) {
      currentMain.innerHTML = newMain.innerHTML;
    }

    if (nextRelativePath !== currentPath) {
      window.history.pushState({}, "", nextRelativePath);
      window.scrollTo({ top: 0, behavior: "auto" });
    } else {
      window.scrollTo({ top: currentScrollY, behavior: "auto" });
    }
  } catch (_error) {
    form.submit();
  } finally {
    if (submitter) {
      submitter.removeAttribute("disabled");
    }
  }
});
