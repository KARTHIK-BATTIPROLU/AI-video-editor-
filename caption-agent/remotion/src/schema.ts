// Canonical props.json contract (MASTER_PROMPT §6) as a zod schema.
// SINGLE SOURCE OF TRUTH: the Remotion <Composition schema=…> validates the
// render against this, and scripts/validate_props.mjs validates props.json
// against this same file before rendering. Drift on either side fails loudly.
// Times are MILLISECONDS; positions are NORMALIZED 0..1.
import { z } from "zod";

export const anchorSchema = z.enum(["center", "lower", "upper"]);
export const animSchema = z.enum(["pop", "fill", "fly", "glitch"]);

export const wordSchema = z.object({
  text: z.string(),
  startMs: z.number(),
  endMs: z.number(),
});

export const pageSchema = z.object({
  startMs: z.number(),
  endMs: z.number(),
  x: z.number(),
  y: z.number(),
  anchor: anchorSchema,
  words: z.array(wordSchema),
});

export const templateSchema = z.object({
  id: z.string(),
  font: z.string(),
  sizePx: z.number(),
  weight: z.number(),
  upper: z.boolean(),
  anim: animSchema,
  baseColor: z.string(),
  activeColor: z.string(),
  enterMs: z.number(),
});

export const propsSchema = z.object({
  videoSrc: z.string(),
  fps: z.number(),
  width: z.number(),
  height: z.number(),
  durationInFrames: z.number(),
  template: templateSchema,
  pages: z.array(pageSchema),
});
