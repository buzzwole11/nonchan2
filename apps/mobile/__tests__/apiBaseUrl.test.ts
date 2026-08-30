/**
 * Where the app decides to send its requests.
 *
 * The case worth protecting: on a real phone `localhost` is the phone, so a hardcoded
 * default points the app at itself and the feed is empty with nothing to say why. The app
 * follows the Expo dev server's host instead, which is the machine running the API.
 */
import Constants from 'expo-constants';
import { Platform } from 'react-native';

import { apiBaseUrl } from '../src/api/useApi';

jest.mock('expo-constants', () => ({ __esModule: true, default: {} }));

const constants = Constants as unknown as {
  expoConfig?: { hostUri?: string; extra?: { apiBaseUrl?: string } };
  expoGoConfig?: { debuggerHost?: string };
};

afterEach(() => {
  jest.restoreAllMocks();
});

beforeEach(() => {
  // The module reads Constants on every call, so clearing the two fields is enough to
  // isolate each case.
  delete constants.expoConfig;
  delete constants.expoGoConfig;
});

describe('apiBaseUrl', () => {
  it('follows the host Expo is serving the bundle from', () => {
    constants.expoConfig = { hostUri: '192.168.1.23:8081' };
    expect(apiBaseUrl()).toBe('http://192.168.1.23:8000');
  });

  it('accepts the older debuggerHost from Expo Go', () => {
    constants.expoGoConfig = { debuggerHost: '10.0.0.5:19000' };
    expect(apiBaseUrl()).toBe('http://10.0.0.5:8000');
  });

  it('strips a scheme and path when the host arrives as a URL', () => {
    constants.expoConfig = { hostUri: 'exp://192.168.1.23:8081/--/discover' };
    expect(apiBaseUrl()).toBe('http://192.168.1.23:8000');
  });

  it('lets an explicit configuration win, for staging and production builds', () => {
    constants.expoConfig = {
      hostUri: '192.168.1.23:8081',
      extra: { apiBaseUrl: 'https://api.papermatch.example' },
    };
    expect(apiBaseUrl()).toBe('https://api.papermatch.example');
  });

  it('falls back to localhost when there is no dev server to ask', () => {
    expect(apiBaseUrl()).toBe('http://localhost:8000');
  });

  it('keeps localhost for a web build served from the same machine', () => {
    constants.expoConfig = { hostUri: 'localhost:8081' };
    expect(apiBaseUrl()).toBe('http://localhost:8000');
  });

  describe('on the web, where there is no manifest to read', () => {
    // Verified against a real page: `hostUri` and `debuggerHost` are both absent when the
    // dev server hands the bundle to a browser. The address bar is what is left.
    const location = globalThis.location;
    const platform = Platform.OS;

    afterEach(() => {
      Object.defineProperty(globalThis, 'location', { value: location, configurable: true });
      (Platform as { OS: string }).OS = platform;
    });

    function servedFrom(host: string) {
      // `Platform.OS` is a plain property in the test environment, so it is set, not spied.
      (Platform as { OS: string }).OS = 'web';
      Object.defineProperty(globalThis, 'location', {
        value: { host } as Location,
        configurable: true,
      });
    }

    it('follows the address the page was served from', () => {
      servedFrom('192.168.1.23:8081');
      expect(apiBaseUrl()).toBe('http://192.168.1.23:8000');
    });

    it('stays on localhost when that is where the browser is', () => {
      servedFrom('localhost:8081');
      expect(apiBaseUrl()).toBe('http://localhost:8000');
    });
  });
});
