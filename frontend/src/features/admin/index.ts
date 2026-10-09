// Public interface of the admin feature.
// PLACEHOLDERS: F5 replaces the users pages, F6 the groups pages, F7 the requests
// queue and F8 the audit page.
import { createElement } from 'react';
import { PlaceholderPage } from './placeholder-page';

export const UsersPage = () => createElement(PlaceholderPage, { title: 'Users' });
export const UserDetailPage = () => createElement(PlaceholderPage, { title: 'User' });
export const GroupsPage = () => createElement(PlaceholderPage, { title: 'Groups' });
export const GroupDetailPage = () => createElement(PlaceholderPage, { title: 'Group' });
export const AdminRequestsPage = () => createElement(PlaceholderPage, { title: 'Access requests' });
export const AuditPage = () => createElement(PlaceholderPage, { title: 'Audit' });
