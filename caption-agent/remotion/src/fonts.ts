// Deterministic, render-gated font loading via @remotion/google-fonts.
// Each loadFont() bundles the font and blocks rendering (delayRender) until it's
// ready, so text metrics are stable across frames — NOT a CDN <link>, which can
// capture frames before the font resolves. We request only the exact weight +
// latin subset each template uses, so the render makes a few requests, not 50+.
import { loadFont as loadAnton } from "@remotion/google-fonts/Anton";
import { loadFont as loadArchivo } from "@remotion/google-fonts/Archivo";
import { loadFont as loadArchivoBlack } from "@remotion/google-fonts/ArchivoBlack";
import { loadFont as loadJetBrains } from "@remotion/google-fonts/JetBrainsMono";

// Weights mirror pipeline/templates.py: Anton 400, Archivo 900 (karaoke),
// Archivo Black 400, JetBrains Mono 800 (glitch).
const anton = loadAnton("normal", { weights: ["400"], subsets: ["latin"] });
const archivo = loadArchivo("normal", { weights: ["900"], subsets: ["latin"] });
const archivoBlack = loadArchivoBlack("normal", { weights: ["400"], subsets: ["latin"] });
const jetbrains = loadJetBrains("normal", { weights: ["800"], subsets: ["latin"] });

// Map the template's human font name -> the loaded CSS font-family.
export const fontFamilyFor = (name: string): string => {
  switch (name) {
    case "Anton":
      return anton.fontFamily;
    case "Archivo":
      return archivo.fontFamily;
    case "Archivo Black":
      return archivoBlack.fontFamily;
    case "JetBrains Mono":
      return jetbrains.fontFamily;
    default:
      return name;
  }
};
