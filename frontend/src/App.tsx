import { AppRoutes } from './routes/AppRoutes'
import { BookmarkProvider } from './store/BookmarkContext'

function App() {
  return (
    <BookmarkProvider>
      <AppRoutes />
    </BookmarkProvider>
  )
}

export default App
