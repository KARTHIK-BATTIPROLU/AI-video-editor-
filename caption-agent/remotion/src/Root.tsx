import React from "react";
import { Composition, CalculateMetadataFunction } from "remotion";
import { CaptionedVideo } from "./CaptionedVideo";
import { propsSchema } from "./schema";
import type { CaptionedVideoProps } from "./types";
import sampleProps from "../public/props.json";

// Default props let the composition render in Studio without --props.
// At render time Python passes --props=./public/props.json which overrides these.
const defaultProps = sampleProps as unknown as CaptionedVideoProps;

// Size the composition to the source video, read from the input props.
const calculateMetadata: CalculateMetadataFunction<CaptionedVideoProps> = ({
  props,
}) => {
  // Hard contract enforcement at RENDER time (Criterion 6). Remotion's `schema`
  // prop only drives the Studio editor/types — it does NOT zod-parse `--props`
  // passed on the CLI. Parsing here runs inside the render pipeline, so a
  // malformed props.json (wrong type / unknown anim / missing field) throws and
  // fails the render loudly instead of producing a wrong video.
  const parsed = propsSchema.parse(props);
  return {
    fps: parsed.fps,
    width: parsed.width,
    height: parsed.height,
    durationInFrames: parsed.durationInFrames,
    props: parsed,
  };
};

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="CaptionedVideo"
      component={CaptionedVideo}
      // schema validates BOTH defaultProps and any --props at render time.
      // A malformed props.json (wrong type / unknown anim / missing field)
      // fails the render loudly instead of rendering garbage. (Criterion 6)
      schema={propsSchema}
      defaultProps={defaultProps}
      calculateMetadata={calculateMetadata}
      // Placeholder dimensions; calculateMetadata overrides them from props.
      fps={defaultProps.fps}
      width={defaultProps.width}
      height={defaultProps.height}
      durationInFrames={defaultProps.durationInFrames}
    />
  );
};
