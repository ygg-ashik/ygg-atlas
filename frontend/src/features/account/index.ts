// Public interface of the account feature (self-service).
// PLACEHOLDERS: F4 replaces My access, My requests and New request; F9 replaces Tokens.
import { createElement } from 'react';
import { PlaceholderPage } from './placeholder-page';

export const MyAccessPage = () => createElement(PlaceholderPage, { title: 'My access' });
export const MyRequestsPage = () => createElement(PlaceholderPage, { title: 'My requests' });
export const NewRequestPage = () => createElement(PlaceholderPage, { title: 'New request' });
export const TokensPage = () =>
  createElement(PlaceholderPage, { title: 'Tokens & connected apps' });
