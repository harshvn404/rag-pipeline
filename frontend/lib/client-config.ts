import { apiBaseUrl } from "./api";

export function apiHost(): string {
  try {
    return new URL(apiBaseUrl()).host;
  } catch {
    return apiBaseUrl();
  }
}
