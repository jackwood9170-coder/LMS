import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Index from './pages/Index'
import LMS from './pages/LMS'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Index />} />
        <Route path="/lms" element={<LMS />} />
      </Routes>
    </BrowserRouter>
  )
}
