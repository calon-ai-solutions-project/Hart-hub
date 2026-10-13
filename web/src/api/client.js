// One place for every call to the Hart Hub API. Session cookie + CSRF token, same origin.

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

let onSignedOut = () => {};
/** The app registers what to do when the session has ended (show the sign-in screen). */
export function whenSignedOut(handler) {
  onSignedOut = handler;
}

const csrfToken = () => (document.cookie.match(/(?:^|; )csrftoken=([^;]+)/) || [])[1] || "";

export async function api(path, { method = "GET", body, quiet = false } = {}) {
  const options = { method, credentials: "same-origin", headers: {} };
  if (method !== "GET") {
    options.headers["X-CSRFToken"] = csrfToken();
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
  }
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new ApiError("Could not reach the server. Check your connection and try again.", 0);
  }
  if ((response.status === 401 || response.status === 403) && !quiet) {
    onSignedOut();
    throw new ApiError("Your session has ended. Please sign in again.", response.status);
  }
  if (response.status === 204) return null;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(data.detail || "Something went wrong. Please try again.", response.status);
  return data;
}

export const auth = {
  me: () => api("/api/auth/me"),
  login: (email, password) => api("/api/auth/login", { method: "POST", body: { email, password }, quiet: true }),
  logout: () => api("/api/auth/logout", { method: "POST" }),
};

const CHATS = "/api/chat/conversations";
export const chats = {
  list: () => api(CHATS),
  create: () => api(CHATS, { method: "POST", body: {} }),
  get: (id) => api(`${CHATS}/${id}`),
  remove: (id) => api(`${CHATS}/${id}`, { method: "DELETE" }),
  send: (id, body) => api(`${CHATS}/${id}/messages`, { method: "POST", body }),
};

export const quotes = {
  request: (listingIds, deposit, conversation) =>
    api("/api/quotes", { method: "POST", body: { listing_ids: listingIds, deposit, conversation } }),
  status: (ids) => api(`/api/quotes?ids=${ids.join(",")}`),
};
