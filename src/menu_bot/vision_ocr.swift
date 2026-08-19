import Foundation
import Vision
import AppKit

struct OCRLine: Codable {
    let text: String
    let confidence: Float
    let x: Double
    let y: Double
    let width: Double
    let height: Double
}

guard CommandLine.arguments.count == 2 else { exit(2) }
let url = URL(fileURLWithPath: CommandLine.arguments[1])
guard let image = NSImage(contentsOf: url), let data = image.tiffRepresentation,
      let bitmap = NSBitmapImageRep(data: data), let cgImage = bitmap.cgImage else { exit(3) }

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["ko-KR", "en-US"]
request.usesLanguageCorrection = true
request.minimumTextHeight = 0.006
try VNImageRequestHandler(cgImage: cgImage).perform([request])

let lines = (request.results ?? []).compactMap { observation -> OCRLine? in
    guard let candidate = observation.topCandidates(1).first else { return nil }
    let box = observation.boundingBox
    return OCRLine(text: candidate.string, confidence: candidate.confidence,
                   x: box.origin.x, y: box.origin.y,
                   width: box.width, height: box.height)
}.sorted {
    let a = $0.y + $0.height, b = $1.y + $1.height
    return abs(a - b) > 0.01 ? a > b : $0.x < $1.x
}
let encoder = JSONEncoder()
encoder.outputFormatting = [.sortedKeys]
FileHandle.standardOutput.write(try encoder.encode(lines))


