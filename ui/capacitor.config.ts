import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'org.reptilearn.app',
  appName: 'ReptiLearn',
  webDir: 'build',
  server: {
    // Allow http:// LAN / SSH-tunnel endpoints (ReptiLearn has no HTTPS by default).
    cleartext: true,
    androidScheme: 'https',
  },
  android: {
    allowMixedContent: true,
  },
};

export default config;
