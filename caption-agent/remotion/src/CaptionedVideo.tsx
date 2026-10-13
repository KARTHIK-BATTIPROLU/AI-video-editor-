import React from "react";
import { AbsoluteFill, OffthreadVideo, staticFile } from "remotion";
import { Captions } from "./Captions";
import type { CaptionedVideoProps } from "./types";

// videoSrc is either a remote URL or a filename living in remotion/public/.
// Python copies the input video into public/ and writes just the filename.
const resolveSrc = (s: string): string =>
  /^https?:\/\//.test(s) ? s : staticFile(s);

export const CaptionedVideo: React.FC<CaptionedVideoProps> = ({
  videoSrc,
  pages,
  template,
  fps,
}) => {
  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      <OffthreadVideo src={resolveSrc(videoSrc)} />
      <Captions pages={pages} template={template} fps={fps} />
    </AbsoluteFill>
  );
};
