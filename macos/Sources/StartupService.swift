import Foundation
import ServiceManagement

enum StartupService {
    static var needsApproval: Bool { SMAppService.mainApp.status == .requiresApproval }
    static func setEnabled(_ enabled: Bool) throws {
        let service = SMAppService.mainApp
        if enabled {
            if service.status != .enabled && service.status != .requiresApproval { try service.register() }
        } else if service.status != .notRegistered { try service.unregister() }
    }
}
