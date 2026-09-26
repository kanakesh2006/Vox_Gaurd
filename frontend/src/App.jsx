import React from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import CallerUI from './CallerUI';
import Dashboard from './Dashboard';

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<CallerUI />} />
        <Route path="/dashboard" element={<Dashboard />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
