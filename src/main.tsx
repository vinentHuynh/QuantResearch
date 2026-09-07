import React from 'react';
import ReactDOM from 'react-dom/client';
import { Provider } from 'react-redux';
import { MantineProvider } from '@mantine/core';
import '@mantine/core/styles.css';
import { store } from './store';
import { App } from './App';
import './styles.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Provider store={store}>
      <MantineProvider
        defaultColorScheme="light"
        theme={{
          primaryColor: 'teal',
          primaryShade: 8,
          fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif',
          headings: { fontFamily: 'Georgia, ui-serif, serif', fontWeight: '600' },
          defaultRadius: 'xs',
        }}
      >
        <App />
      </MantineProvider>
    </Provider>
  </React.StrictMode>,
);
