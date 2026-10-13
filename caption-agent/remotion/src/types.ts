// TS types for the props.json contract, DERIVED from the canonical zod schema in
// schema.ts (single source of truth). Component code keeps importing these names
// as types; Root.tsx imports the schemas themselves to validate the render.
import { z } from "zod";
import {
  anchorSchema,
  animSchema,
  wordSchema,
  pageSchema,
  templateSchema,
  propsSchema,
} from "./schema";

export {
  anchorSchema,
  animSchema,
  wordSchema,
  pageSchema,
  templateSchema,
  propsSchema,
};

export type Anchor = z.infer<typeof anchorSchema>;
export type AnimId = z.infer<typeof animSchema>;
export type CaptionWord = z.infer<typeof wordSchema>;
export type CaptionPage = z.infer<typeof pageSchema>;
export type TemplateProps = z.infer<typeof templateSchema>;
export type CaptionedVideoProps = z.infer<typeof propsSchema>;
