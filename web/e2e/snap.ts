/** Screenshot runner: `npm run snap <scene>`.
 *
 * Assumes a server is already serving the UI at OPPOSABLE_BASE (default :8734).
 */
import { withBrowser } from "./shoot";
import { scenes } from "./scenes";

const name = process.argv[2];
const scene = name ? scenes[name] : undefined;

if (!scene) {
  console.error(`usage: npm run snap <scene>\nscenes: ${Object.keys(scenes).join(", ")}`);
  process.exit(1);
}

console.log(`scene: ${name}`);
await withBrowser(scene);
