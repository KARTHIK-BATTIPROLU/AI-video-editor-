import { Config } from "@remotion/cli/config";

// Frame-by-frame H.264 output. Captions are burned into the base video.
Config.setVideoImageFormat("jpeg");
Config.setOverwriteOutput(true);
Config.setConcurrency(2);
