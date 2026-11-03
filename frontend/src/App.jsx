import { useEffect, useRef } from 'react'
import {
  Navigate,
  Route,
  Routes,
  useNavigate,
  useParams,
  useSearchParams,
} from 'react-router-dom'
import { useAuth } from './context/AuthContext'
import { useUI } from './context/UIContext'
import { DOMAINS, hasDomainAccess } from './utils/access'
import AppShell from './layouts/AppShell'
import ChannelLayout from './layouts/ChannelLayout'
import ClientHomeLayout from './layouts/ClientHomeLayout'
import ClientLayout from './layouts/ClientLayout'
import SocialMediaLayout from './layouts/SocialMediaLayout'
import WebsiteLayout from './layouts/WebsiteLayout'
import AdminDashboard from './pages/AdminDashboard'
import ChannelOverview from './pages/ChannelOverview'
import ChannelSettings from './pages/ChannelSettings'
import ChannelVideos from './pages/ChannelVideos'
import ClientHub from './pages/ClientHub'
import ClientOverview from './pages/ClientOverview'
import ClientSettings from './pages/ClientSettings'
import ClientProfileLayout from './layouts/ClientProfileLayout'
import ClientTrackerLayout from './layouts/ClientTrackerLayout'
import ClientDoctorReference from './pages/ClientDoctorReference'
import ClientPracticeDetails from './pages/ClientPracticeDetails'
import ClientDeliverables from './pages/ClientDeliverables'
import ClientCredentials from './pages/ClientCredentials'
import ClientAccess from './pages/ClientAccess'
import ClientContentPlan from './pages/ClientContentPlan'
import ClientReportDetail from './pages/ClientReportDetail'
import ClientReports from './pages/ClientReports'
import ClientScripts from './pages/ClientScripts'
import ClientPostVideo from './pages/ClientPostVideo'
import ClientSocialGenerate from './pages/ClientSocialGenerate'
import ClientSocialInstagram from './pages/ClientSocialInstagram'
import ClientSocialFacebook from './pages/ClientSocialFacebook'
import ClientYoutubeConnection from './pages/ClientYoutubeConnection'
import ClientSocialSchedule from './pages/ClientSocialSchedule'
import ClientSocialFestivals from './pages/ClientSocialFestivals'
import WebsiteOverview from './pages/WebsiteOverview'
import WebsiteCollections from './pages/WebsiteCollections'
import WebsiteEntries from './pages/WebsiteEntries'
import WebsiteMedia from './pages/WebsiteMedia'
import WebsiteReports from './pages/WebsiteReports'
import WebsiteDeployment from './pages/WebsiteDeployment'
import ClientWeeklyTracker from './pages/ClientWeeklyTracker'
import ClientCustomTracker from './pages/ClientCustomTracker'
import PocWeeklyTracker from './pages/PocWeeklyTracker'
import EditTracker from './pages/EditTracker'
import EditTrackerSettings from './pages/EditTrackerSettings'
import ClientVideos from './pages/ClientVideos'
import ClientsIndex from './pages/ClientsIndex'
import LoginPage from './pages/LoginPage'
import PlugRoot from './plug/PlugRoot'

function RequireAuth({ children }) {
  const { token, user, loading } = useAuth()

  if (loading) {
    return (
      <div className="login-page">
        <div className="login-body">
          <p className="text-muted">Loading...</p>
        </div>
      </div>
    )
  }

  if (!token || !user) {
    return <Navigate to="/login" replace />
  }

  return children
}

function HomeRedirect() {
  const { user } = useAuth()
  if (user?.active_client_id) {
    return <Navigate to={`/clients/${user.active_client_id}`} replace />
  }
  return <Navigate to="/clients" replace />
}

function OAuthSuccessHandler() {
  const { token, refreshUser } = useAuth()
  const { toast } = useUI()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const handled = useRef(false)

  useEffect(() => {
    if (searchParams.get('google_auth') !== 'success' || handled.current) return
    handled.current = true

    ;(async () => {
      const me = token ? await refreshUser() : null
      toast('YouTube channel linked successfully!', 'success')
      setSearchParams({}, { replace: true })
      const clientId = me?.active_client_id
      navigate(
        clientId ? `/clients/${clientId}/profile/connections/youtube` : '/clients',
        { replace: true },
      )
    })()
  }, [searchParams, token, refreshUser, toast, setSearchParams, navigate])

  return null
}

function ClientIdGuard({ children }) {
  const { clientId } = useParams()
  const { user } = useAuth()
  const exists = (user?.clients || []).some((c) => c.id === clientId)
  if (user?.clients && !exists) {
    return <Navigate to="/clients" replace />
  }
  return children
}

function DomainGuard({ domain, children }) {
  const { clientId } = useParams()
  const { user } = useAuth()
  const client = (user?.clients || []).find((c) => c.id === clientId)
  if (user?.clients && client && !hasDomainAccess(client, domain)) {
    return <Navigate to={`/clients/${clientId}`} replace />
  }
  return children
}

function RedirectToKeywords() {
  const { clientId } = useParams()
  return <Navigate to={`/clients/${clientId}/profile/keywords`} replace />
}

function RedirectToPreferences() {
  const { clientId } = useParams()
  return <Navigate to={`/clients/${clientId}/profile/preferences`} replace />
}

function RedirectToClientTracker() {
  const { clientId } = useParams()
  return <Navigate to={`/clients/${clientId}/tracker`} replace />
}

function RedirectToInstagramConnection() {
  const { clientId } = useParams()
  return <Navigate to={`/clients/${clientId}/profile/connections/instagram`} replace />
}

function RedirectToFacebookConnection() {
  const { clientId } = useParams()
  return <Navigate to={`/clients/${clientId}/profile/connections/facebook`} replace />
}

function RedirectToClientCustomTracker() {
  const { clientId } = useParams()
  return <Navigate to={`/clients/${clientId}/tracker/custom`} replace />
}

function WebsiteCollectionEntriesRedirect() {
  const { clientId, collectionId } = useParams()
  const qs = collectionId ? `?collection=${encodeURIComponent(collectionId)}` : ''
  return <Navigate to={`/clients/${clientId}/website/entries${qs}`} replace />
}

export default function App() {
  return (
    <>
      <OAuthSuccessHandler />
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/admin" element={<AdminDashboard />} />
        <Route path="/plug/*" element={<PlugRoot />} />

        <Route
          path="/"
          element={
            <RequireAuth>
              <HomeRedirect />
            </RequireAuth>
          }
        />

        <Route
          element={
            <RequireAuth>
              <AppShell />
            </RequireAuth>
          }
        >
          <Route path="/clients" element={<ClientsIndex />} />
          <Route path="/tracker" element={<PocWeeklyTracker />} />
          <Route path="/edit-tracker" element={<EditTracker />} />
          <Route path="/edit-tracker/settings" element={<EditTrackerSettings />} />
          <Route path="/tracker/:clientId" element={<Navigate to="/tracker" replace />} />
          <Route path="/tracker/:clientId/custom" element={<Navigate to="/tracker" replace />} />
        </Route>

        <Route
          path="/clients/:clientId"
          element={
            <RequireAuth>
              <ClientIdGuard>
                <ClientHomeLayout />
              </ClientIdGuard>
            </RequireAuth>
          }
        >
          <Route index element={<ClientHub />} />
        </Route>

        <Route
          path="/clients/:clientId/videos"
          element={
            <RequireAuth>
              <ClientIdGuard>
                <DomainGuard domain={DOMAINS.VIDEOS}>
                  <ClientLayout />
                </DomainGuard>
              </ClientIdGuard>
            </RequireAuth>
          }
        >
          <Route index element={<ClientOverview />} />
          <Route path="library" element={<ClientVideos />} />
          <Route path="post" element={<ClientPostVideo />} />
          <Route path="content-plan" element={<ClientContentPlan />} />
          <Route path="tracker" element={<RedirectToClientTracker />} />
          <Route path="tracker/custom" element={<RedirectToClientCustomTracker />} />
          <Route path="reports" element={<ClientReports />} />
          <Route path="reports/:reportId" element={<ClientReportDetail />} />
          <Route path="scripts" element={<ClientScripts />} />
          <Route path="settings" element={<RedirectToKeywords />} />
          <Route path="channels/:channelId" element={<ChannelLayout />}>
            <Route index element={<ChannelOverview />} />
            <Route path="library" element={<ChannelVideos />} />
            <Route path="settings" element={<ChannelSettings />} />
          </Route>
        </Route>

        <Route
          path="/clients/:clientId/tracker"
          element={
            <RequireAuth>
              <ClientIdGuard>
                <ClientTrackerLayout />
              </ClientIdGuard>
            </RequireAuth>
          }
        >
          <Route index element={<ClientWeeklyTracker />} />
          <Route path="custom" element={<ClientCustomTracker />} />
        </Route>

        <Route
          path="/clients/:clientId/profile"
          element={
            <RequireAuth>
              <ClientIdGuard>
                <ClientProfileLayout />
              </ClientIdGuard>
            </RequireAuth>
          }
        >
          <Route index element={<Navigate to="practice" replace />} />
          <Route path="practice" element={<ClientPracticeDetails />} />
          <Route path="preferences" element={<ClientDoctorReference />} />
          <Route path="doctor-reference" element={<RedirectToPreferences />} />
          <Route path="deliverables" element={<ClientDeliverables />} />
          <Route path="connections" element={<Navigate to="youtube" replace />} />
          <Route path="connections/youtube" element={<ClientYoutubeConnection />} />
          <Route path="connections/instagram" element={<ClientSocialInstagram />} />
          <Route path="connections/facebook" element={<ClientSocialFacebook />} />
          <Route path="keywords" element={<ClientSettings />} />
          <Route path="youtube-settings" element={<RedirectToKeywords />} />
          <Route path="credentials" element={<ClientCredentials />} />
          <Route path="access" element={<ClientAccess />} />
        </Route>

        <Route
          path="/clients/:clientId/social"
          element={
            <RequireAuth>
              <ClientIdGuard>
                <DomainGuard domain={DOMAINS.SOCIALMEDIA}>
                  <SocialMediaLayout />
                </DomainGuard>
              </ClientIdGuard>
            </RequireAuth>
          }
        >
          <Route index element={<Navigate to="generate" replace />} />
          <Route path="instagram" element={<RedirectToInstagramConnection />} />
          <Route path="facebook" element={<RedirectToFacebookConnection />} />
          <Route path="generate" element={<ClientSocialGenerate />} />
          <Route path="schedule" element={<ClientSocialSchedule />} />
          <Route path="festivals" element={<ClientSocialFestivals />} />
        </Route>

        <Route
          path="/clients/:clientId/website"
          element={
            <RequireAuth>
              <ClientIdGuard>
                <DomainGuard domain={DOMAINS.WEBSITE}>
                  <WebsiteLayout />
                </DomainGuard>
              </ClientIdGuard>
            </RequireAuth>
          }
        >
          <Route index element={<WebsiteOverview />} />
          <Route path="collections" element={<WebsiteCollections />} />
          <Route
            path="collections/:collectionId"
            element={<WebsiteCollectionEntriesRedirect />}
          />
          <Route path="entries" element={<WebsiteEntries />} />
          <Route path="media" element={<WebsiteMedia />} />
          <Route path="reports" element={<WebsiteReports />} />
          <Route path="deployment" element={<WebsiteDeployment />} />
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  )
}
