import { Navigate, Route, Routes } from "react-router-dom";
import { AnalysisProgressPage } from "../pages/AnalysisProgressPage/AnalysisProgressPage";
import { BookmarksPage } from "../pages/BookmarksPage/BookmarksPage";
import { CompanyProfilePage } from "../pages/CompanyProfilePage/CompanyProfilePage";
import { LandingPage } from "../pages/LandingPage/LandingPage";
import { LoginPage } from "../pages/LoginPage/LoginPage";
import { MatchDetailPage } from "../pages/MatchDetailPage/MatchDetailPage";
import { MatchHistoryPage } from "../pages/MatchHistoryPage/MatchHistoryPage";
import { MyPage } from "../pages/MyPage/MyPage";
import { NoticeDetailPage } from "../pages/NoticeDetailPage/NoticeDetailPage";
import { ResultsPage } from "../pages/ResultsPage/ResultsPage";
import { UploadPage } from "../pages/UploadPage/UploadPage";
import { MainLayout } from "../layouts/MainLayout/MainLayout";
import { PATHS } from "./paths";

export function AppRoutes() {
  return (
    <Routes>
      <Route path={PATHS.LANDING} element={<LandingPage />} />
      <Route element={<MainLayout />}>
        <Route path={PATHS.LOGIN} element={<LoginPage />} />
        <Route path={PATHS.COMPANY_PROFILE} element={<CompanyProfilePage />} />
        <Route path={PATHS.UPLOAD} element={<UploadPage />} />
        <Route path={PATHS.ANALYSIS} element={<AnalysisProgressPage />} />
        <Route path={PATHS.RESULTS} element={<ResultsPage />} />
        <Route path={PATHS.MATCH_HISTORY} element={<MatchHistoryPage />} />
        <Route path={PATHS.RESULT_DETAIL} element={<MatchDetailPage />} />
        <Route path={PATHS.NOTICE_DETAIL} element={<NoticeDetailPage />} />
        <Route path={PATHS.BOOKMARKS} element={<BookmarksPage />} />
        <Route path={PATHS.MYPAGE} element={<MyPage />} />
      </Route>
      <Route path="*" element={<Navigate to={PATHS.LANDING} replace />} />
    </Routes>
  );
}
