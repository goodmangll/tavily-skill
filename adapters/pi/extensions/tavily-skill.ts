import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

/** Make the platform-agnostic skills directory discoverable by Pi. */
export default function tavilySkill(pi: ExtensionAPI) {
  pi.on("resources_discover", async () => ({
    skillPaths: [new URL("../../../skills", import.meta.url).pathname],
  }));
}
