// jest-dom adds custom jest matchers for asserting on DOM nodes.
import '@testing-library/jest-dom';
import { TextEncoder, TextDecoder } from 'util';

// react-router v7 needs these, and jsdom doesn't provide them.
if (!global.TextEncoder) global.TextEncoder = TextEncoder;
if (!global.TextDecoder) global.TextDecoder = TextDecoder;
if (!global.URL.createObjectURL) global.URL.createObjectURL = () => 'blob:preview';
