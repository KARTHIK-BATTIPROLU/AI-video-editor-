import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
} from "remotion";
import { fontFamilyFor } from "./fonts";
import type { Anchor, CaptionPage, CaptionWord, TemplateProps } from "./types";

const clamp01 = (v: number) => Math.max(0, Math.min(1, v));

// Vertical alignment of the page block relative to its normalized y line.
const translateForAnchor = (anchor: Anchor): string => {
  switch (anchor) {
    case "upper":
      return "translate(-50%, 0%)";
    case "lower":
      return "translate(-50%, -100%)";
    case "center":
    default:
      return "translate(-50%, -50%)";
  }
};

export const Captions: React.FC<{
  pages: CaptionPage[];
  template: TemplateProps;
  fps: number;
}> = ({ pages, template, fps }) => {
  const frame = useCurrentFrame();
  const frameMs = (frame / fps) * 1000;
  const leadMs = template.enterMs;

  return (
    <AbsoluteFill>
      {pages.map((page, i) => {
        const visible =
          frameMs >= page.startMs - leadMs && frameMs <= page.endMs + 200;
        if (!visible) return null;
        return (
          <PageBlock
            key={i}
            page={page}
            template={template}
            frameMs={frameMs}
            fps={fps}
          />
        );
      })}
    </AbsoluteFill>
  );
};

const PageBlock: React.FC<{
  page: CaptionPage;
  template: TemplateProps;
  frameMs: number;
  fps: number;
}> = ({ page, template, frameMs, fps }) => {
  return (
    <div
      style={{
        position: "absolute",
        left: `${page.x * 100}%`,
        top: `${page.y * 100}%`,
        transform: translateForAnchor(page.anchor),
        display: "flex",
        flexWrap: "wrap",
        justifyContent: "center",
        alignItems: "center",
        gap: `0.28em`,
        // Hug the text and sit it on a translucent scrim so white captions stay
        // legible over bright/busy backgrounds (e.g. a light patterned shirt in
        // the lower third) instead of washing out.
        width: "fit-content",
        maxWidth: "86%",
        boxSizing: "border-box",
        padding: "0.16em 0.5em",
        borderRadius: "0.3em",
        backgroundColor: "rgba(0, 0, 0, 0.5)",
        textAlign: "center",
        lineHeight: 1.15,
      }}
    >
      {page.words.map((word, i) => (
        <Word
          key={i}
          word={word}
          index={i}
          template={template}
          frameMs={frameMs}
          fps={fps}
        />
      ))}
    </div>
  );
};

const Word: React.FC<{
  word: CaptionWord;
  index: number;
  template: TemplateProps;
  frameMs: number;
  fps: number;
}> = ({ word, index, template, frameMs, fps }) => {
  const active = frameMs >= word.startMs && frameMs <= word.endMs;
  const startFrame = (word.startMs / 1000) * fps;
  const enterProgress = clamp01(
    (frameMs - word.startMs) / Math.max(1, template.enterMs),
  );

  const base: React.CSSProperties = {
    fontFamily: fontFamilyFor(template.font),
    fontWeight: template.weight,
    fontSize: template.sizePx,
    textTransform: template.upper ? "uppercase" : "none",
    whiteSpace: "pre",
    display: "inline-block",
    willChange: "transform, opacity",
  };

  const text = template.upper ? word.text.toUpperCase() : word.text;

  switch (template.anim) {
    case "pop": {
      const enter = spring({
        frame: frameMs / 1000 * fps - startFrame,
        fps,
        config: { damping: 11, stiffness: 150, mass: 0.6 },
      });
      const scale =
        interpolate(enter, [0, 1], [0.55, 1]) * (active ? 1.08 : 1);
      const opacity = interpolate(enter, [0, 0.6], [0, 1], {
        extrapolateRight: "clamp",
      });
      return (
        <span
          style={{
            ...base,
            color: active ? template.activeColor : template.baseColor,
            opacity,
            transform: `scale(${scale})`,
            textShadow: "0 2px 10px rgba(0,0,0,0.55)",
          }}
        >
          {text}
        </span>
      );
    }

    case "fill": {
      // Word slides up + fades in; active word fills left->right.
      const translateY = interpolate(enterProgress, [0, 1], [14, 0]);
      const opacity = interpolate(enterProgress, [0, 1], [0, 1]);
      const fillPct =
        clamp01((frameMs - word.startMs) / Math.max(1, word.endMs - word.startMs)) *
        100;
      return (
        <span
          style={{
            ...base,
            opacity,
            transform: `translateY(${translateY}px)`,
            backgroundImage: `linear-gradient(90deg, ${template.activeColor} ${fillPct}%, ${template.baseColor} ${fillPct}%)`,
            WebkitBackgroundClip: "text",
            backgroundClip: "text",
            color: "transparent",
            textShadow: "0 2px 10px rgba(0,0,0,0.45)",
          }}
        >
          {text}
        </span>
      );
    }

    case "fly": {
      const enter = spring({
        frame: frameMs / 1000 * fps - startFrame,
        fps,
        config: { damping: 13, stiffness: 120, mass: 0.7 },
      });
      const dir = index % 2 === 0 ? -1 : 1;
      const tx = interpolate(enter, [0, 1], [dir * 70, 0]);
      const ty = interpolate(enter, [0, 1], [44, 0]);
      const rot = interpolate(enter, [0, 1], [dir * 14, 0]);
      const sizeMul = [1, 1.28, 0.82][index % 3];
      return (
        <span
          style={{
            ...base,
            fontSize: template.sizePx * sizeMul,
            color: active ? template.activeColor : template.baseColor,
            opacity: interpolate(enter, [0, 0.7], [0, 1], {
              extrapolateRight: "clamp",
            }),
            transform: `translate(${tx}px, ${ty}px) rotate(${rot}deg)`,
            textShadow: "0 2px 10px rgba(0,0,0,0.55)",
          }}
        >
          {text}
        </span>
      );
    }

    case "glitch": {
      // Chromatic split that decays as the word enters; sine jitter while active.
      const offset = interpolate(enterProgress, [0, 1], [8, 0]);
      const jitter = active ? Math.sin(frameMs / 40) * 1.5 : 0;
      const opacity = interpolate(enterProgress, [0, 0.4], [0, 1], {
        extrapolateRight: "clamp",
      });
      return (
        <span
          style={{
            ...base,
            color: active ? template.activeColor : template.baseColor,
            opacity,
            transform: `translateX(${jitter}px)`,
            textShadow: `${offset}px 0 #ff2e63, ${-offset}px 0 #08f7fe`,
          }}
        >
          {text}
        </span>
      );
    }

    default:
      return (
        <span style={{ ...base, color: template.baseColor }}>{text}</span>
      );
  }
};
